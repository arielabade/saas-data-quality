"""Cada regra de limpeza com um caso positivo (deve agir) e um negativo (não deve agir)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from dq.clean import dedup, devices, nulls, outliers, test_accounts, timestamps, usage_limits
from dq.clean.standardize import parse_client_ts, standardize, to_cents
from dq.domain import cpf_valid, normalize_device_type, normalize_uf
from dq.load import quarantine
from dq.state import scd

T = pd.Timestamp


# ------------------------------------------------------------------ padronização (staging)
def test_parse_client_ts_por_formato():
    s = pd.Series(["2024-02-03 00:00:00", "2024-02-03T00:00:00-03:00", "2024-02-03T03:00:00Z", "2024-02-03T00:00:00", None])
    ts, amb = parse_client_ts(s)
    assert ts.iloc[0] == T("2024-02-03 00:00:00")      # TV: UTC por contrato (não herda offset de outra linha)
    assert ts.iloc[1] == ts.iloc[2] == T("2024-02-03 03:00:00")
    assert amb.tolist() == [False, False, False, True, False]
    assert pd.isna(ts.iloc[4])


def test_centavos_sem_erro_de_ponto_flutuante():
    assert to_cents(pd.Series([39.9, 0.1 + 0.2, 18.90])).tolist() == [3990, 30, 1890]


def test_textos_canonicos():
    assert normalize_device_type(pd.Series(["Smart TV", "smartphone", "WEB", "tablet "])).tolist() == ["tv", "celular", "web", "tablet"]
    assert normalize_uf(pd.Series(["sp", " RJ", "Bahia", "XX"])).tolist()[:3] == ["SP", "RJ", "BA"]
    assert pd.isna(normalize_uf(pd.Series(["XX"])).iloc[0])


def test_milissegundos_do_app6_movel(tiny_raw):
    st, stats = standardize(tiny_raw)
    r = st["reproducoes"].set_index("reproducao_id")
    assert r.loc[1, "segundos_assistidos"] == 1200          # 1.200.000 ms no celular com app 6.x
    assert r.loc[2, "segundos_assistidos"] == 1500          # TV com app 6.x: já em segundos
    assert stats["reproducoes_ms_convertidas"] == 1


# ------------------------------------------------------------------ contas internas
def _contas(**over):
    base = dict(conta_id=[1, 2], email=["ana.souza@webmail.example.com", "joao@mail.example.com"],
                nome_titular=["Ana Souza", "João Lima"], cpf=["529.982.247-25", "111.444.777-35"],
                criada_em=[T("2024-01-01"), T("2024-02-01")])
    base.update(over)
    return pd.DataFrame(base)


def test_conta_teste_por_email_e_cpf_invalido():
    c = _contas(email=["qa.automacao+12@webmail.example.com", "joao@mail.example.com"], cpf=["529.982.247-25", "123.456.789-00"])
    found = test_accounts.detect(c, pd.DataFrame({"conta_id": [], "ip": []}))
    assert set(found["conta_id"]) == {1, 2}


def test_cliente_comum_nao_e_teste():
    found = test_accounts.detect(_contas(), pd.DataFrame({"conta_id": [1, 2], "ip": ["177.1.1.1", "177.1.1.2"]}))
    assert found.empty


def test_cpf_duplicado_marca_a_conta_mais_nova_e_rede_qa():
    c = _contas(cpf=["529.982.247-25", "529.982.247-25"])
    found = test_accounts.detect(c, pd.DataFrame({"conta_id": [1], "ip": ["10.250.3.4"]}))
    assert set(found["conta_id"]) == {1, 2}
    assert "rede_qa" in found.set_index("conta_id").loc[1, "motivo"]
    assert "cpf_duplicado" in found.set_index("conta_id").loc[2, "motivo"]


def test_cpf_valido():
    assert cpf_valid(pd.Series(["529.982.247-25", "111.111.111-11", "529.982.247-26"])).tolist() == [True, False, False]


# ------------------------------------------------------------------ deduplicação
def _pag():
    return pd.DataFrame({
        "pagamento_id": [1, 2, 3, 4, 5], "fatura_id": pd.array([10, 10, 10, 10, 11], dtype="Int64"),
        "tipo": ["cobranca"] * 5, "tentativa": [1, 1, 2, 1, 1], "status": ["aprovado", "aprovado", "aprovado", "aprovado", "aprovado"],
        "valor_centavos": pd.array([3990] * 5, dtype="Int64"),
        "processado_em": [T("2024-01-01 10:00"), T("2024-01-01 10:01"), T("2024-01-03 10:00"), T("2024-01-02 10:00"), T("2024-01-01 10:00")],
    })


def test_webhook_duplicado_na_janela_e_removido():
    out, f = dedup.dedup_payments(_pag(), ["fatura_id", "tipo", "tentativa", "status", "valor_centavos"], 3600)
    assert set(f["chave"]) == {2}


def test_outra_tentativa_ou_fora_da_janela_fica():
    out, _ = dedup.dedup_payments(_pag(), ["fatura_id", "tipo", "tentativa", "status", "valor_centavos"], 3600)
    assert {3, 4, 5} <= set(out["pagamento_id"])   # tentativa 2; mesma chave um dia depois; outra fatura


def test_replay_de_lote_removido_pela_chave_natural():
    r = pd.DataFrame({"reproducao_id": [1, 2, 3], "perfil_id": [7, 7, 7], "dispositivo_id": [3, 3, 3], "titulo_id": [5, 5, 5],
                      "episodio_id": pd.array([None, None, None], dtype="Int64"),
                      "inicio_em": [T("2024-01-01 20:00"), T("2024-01-01 20:00"), T("2024-01-01 22:00")],
                      "recebido_em": [T("2024-01-01 21:00"), T("2024-01-02 21:00"), T("2024-01-01 23:00")]})
    out, f = dedup.dedup_usage(r, ["perfil_id", "dispositivo_id", "titulo_id", "episodio_id", "inicio_em"], "reproducao_id", "reproducoes")
    assert f["chave"].tolist() == [2] and set(out["reproducao_id"]) == {1, 3}


# ------------------------------------------------------------------ fuso e relógio
def _usage(n=30, skew_h=0.0, ambiguous=False, dev=1):
    t = pd.date_range("2024-03-01 20:00", periods=n, freq="D")
    return pd.DataFrame({"sessao_id": range(n), "dispositivo_id": dev, "conta_id": pd.array([1] * n, dtype="Int64"),
                         "inicio_em": t, "fim_em": t + pd.Timedelta(hours=1),
                         "recebido_em": t + pd.Timedelta(hours=1, seconds=5) + pd.Timedelta(hours=skew_h),
                         "ts_sem_fuso": ambiguous})


def test_fuso_sem_offset_convertido_para_utc():
    df, f = timestamps.fix_timezone(_usage(3, ambiguous=True), pd.Series({1: "America/Sao_Paulo"}), "sessoes_app", "sessao_id")
    assert df["inicio_em"].iloc[0] == T("2024-03-01 23:00") and len(f) == 3


def test_fuso_com_offset_nao_mexe():
    df, f = timestamps.fix_timezone(_usage(3), pd.Series({1: "America/Sao_Paulo"}), "sessoes_app", "sessao_id")
    assert df["inicio_em"].iloc[0] == T("2024-03-01 20:00") and f.empty


def test_relogio_atrasado_corrigido_e_aparelho_sadio_nao():
    bad, ok = _usage(30, skew_h=5, dev=1), _usage(30, dev=2)
    prof = timestamps.clock_profile([pd.concat([bad, ok])], 30, 0.6, 2023)
    assert prof.loc[1, "relogio_errado"] and not prof.loc[2, "relogio_errado"]
    fixed, f = timestamps.fix_clock(bad.copy(), prof, "sessoes_app", "sessao_id", 2023)
    assert fixed["inicio_em"].iloc[0] == T("2024-03-02 01:00") and len(f) == 30


def test_atrasado_isolado_nao_e_relogio():
    u = _usage(30)
    u.loc[3, "recebido_em"] += pd.Timedelta(days=5)          # sincronização offline
    prof = timestamps.clock_profile([u], 30, 0.6, 2023)
    assert not prof.loc[1, "relogio_errado"]
    assert len(timestamps.mark_late(u, "sessoes_app", "sessao_id")) == 1


def test_relogio_zerado_reconstruido_pela_hora_do_servidor():
    u = _usage(2)
    u.loc[0, ["inicio_em", "fim_em"]] = [T("2000-01-05 10:00"), T("2000-01-05 11:00")]
    prof = timestamps.clock_profile([u], 30, 0.6, 2023)
    fixed, f = timestamps.fix_clock(u, prof, "sessoes_app", "sessao_id", 2023)
    assert fixed["inicio_em"].iloc[0].year == 2024 and "relogio_zerado" in set(f["regra"])


# ------------------------------------------------------------------ dispositivos
def _dev_sessions(second_start):
    d = pd.DataFrame({"dispositivo_id": [1, 2], "conta_id": [9, 9], "tipo": ["celular", "celular"], "plataforma": ["a", "a"]})
    s = pd.DataFrame({"dispositivo_id": [1, 1, 2, 2],
                      "inicio_em": [T("2024-01-01"), T("2024-03-01"), T(second_start), T("2024-06-01")]})
    return d, s


def test_reinstalacao_unifica_id():
    m, f = devices.unify(*_dev_sessions("2024-03-05"), slack_days=14)
    assert m.to_dict() == {2: 1}


def test_dois_celulares_em_paralelo_nao_unifica():
    m, _ = devices.unify(*_dev_sessions("2024-02-01"), slack_days=14)
    assert m.empty


# ------------------------------------------------------------------ limites físicos
LIM = {"fator_duracao": 1.05, "horas_dia_dispositivo": 24, "sessao_folga_min": 10}


def _plays():
    t = T("2024-05-01 20:00")
    return pd.DataFrame({"reproducao_id": [1, 2, 3], "sessao_id": pd.array([1, 1, 1], dtype="Int64"), "dispositivo_id": [1, 1, 1],
                         "inicio_em": [t, t + pd.Timedelta(hours=1), t + pd.Timedelta(hours=2)],
                         "fim_em": [t + pd.Timedelta(minutes=50), t + pd.Timedelta(hours=1, minutes=40), t + pd.Timedelta(hours=12)],
                         "segundos_assistidos": [-300, 2000, 40000], "duracao_conteudo_seg": [3600.0, 2400.0, 3000.0],
                         "percentual_concluido": [0.0, 83.0, 100.0]})


def test_negativo_corrigido_maior_que_conteudo_limitado_normal_intacto():
    s = pd.DataFrame({"sessao_id": [1], "fim_em": [T("2024-05-02 09:00")]})
    r, s2, f = usage_limits.apply_limits(_plays(), s, LIM)
    assert r["segundos_assistidos"].tolist() == [3000, 2000, 3000]
    assert set(f["regra"]) >= {"tempo_negativo", "tempo_maior_que_conteudo", "sessao_aberta_demais"}
    assert 2 not in set(f.loc[f["tabela"] == "reproducoes", "chave"])


def test_mais_de_24h_por_aparelho_no_dia_limitado():
    t = T("2024-05-01 00:00")
    r = pd.DataFrame({"reproducao_id": range(4), "sessao_id": pd.array([1] * 4, dtype="Int64"), "dispositivo_id": 1,
                      "inicio_em": [t] * 4, "fim_em": [t + pd.Timedelta(hours=10)] * 4, "segundos_assistidos": [36000] * 4,
                      "duracao_conteudo_seg": [np.nan] * 4, "percentual_concluido": 50.0})
    out, _, f = usage_limits.apply_limits(r, pd.DataFrame({"sessao_id": [1], "fim_em": [t + pd.Timedelta(hours=10)]}), LIM)
    assert out["segundos_assistidos"].sum() <= 24 * 3600 and len(f[f["regra"] == "mais_de_24h_por_aparelho"]) == 4


# ------------------------------------------------------------------ preço (SCD2)
def _precos():
    return pd.DataFrame({"preco_id": [1, 2], "plano_id": pd.array([2, 2], dtype="Int64"), "item": "assinatura",
                         "periodicidade": "mensal", "valor_centavos": pd.array([3990, 4490], dtype="Int64"), "moeda": "BRL",
                         "vigencia_inicio": [T("2023-01-01"), T("2024-08-01")], "vigencia_fim": [T("2024-07-31"), pd.NaT]})


def test_scd2_versiona_e_corrige_preco_vencido():
    dim = scd.build_price_scd(_precos())
    assert dim["versao"].tolist() == [1, 2] and dim["atual"].tolist() == [False, True]
    f = pd.DataFrame({"fatura_id": [1, 2], "preco_id": [1, 2], "periodo_inicio": [T("2024-09-10"), T("2024-09-10")],
                      "bruto_centavos": pd.array([3990, 4490], dtype="Int64"), "desconto_centavos": pd.array([0, 0], dtype="Int64"),
                      "membro_extra_centavos": pd.array([0, 0], dtype="Int64"), "total_centavos": pd.array([3990, 4490], dtype="Int64")})
    p = pd.DataFrame({"pagamento_id": [7], "fatura_id": pd.array([1], dtype="Int64"), "tipo": ["cobranca"], "valor_centavos": pd.array([3990], dtype="Int64")})
    f2, p2, fl = scd.check_invoices(f, p, dim)
    assert f2.loc[0, "total_centavos"] == 4490 and p2.loc[0, "valor_centavos"] == 4490
    assert set(fl.loc[fl["tabela"] == "faturas", "chave"]) == {1}     # a fatura 2 já estava certa


# ------------------------------------------------------------------ nulos
def test_mecanismo_mar_detectado_e_mcar_nao():
    rng = np.random.default_rng(0)
    n = 4000
    first = np.where(rng.random(n) < 0.3, "tv", "celular")
    contas = pd.DataFrame({"conta_id": range(n), "canal_aquisicao_id": rng.integers(1, 7, n),
                           "uf": np.where((first == "tv") & (rng.random(n) < 0.7), None, "SP"),
                           "telefone": np.where(rng.random(n) < 0.08, None, "9"), "data_nascimento": "x", "cep": "x"})
    disp = pd.DataFrame({"conta_id": range(n), "tipo": first, "registrado_em": T("2024-01-01")})
    ass = pd.DataFrame({"conta_id": range(n), "plano_id": 1, "iniciada_em": T("2024-01-01")})
    rep = nulls.mechanism_report(contas, disp, ass, columns=("uf", "telefone")).set_index("coluna")
    assert rep.loc["uf", "mecanismo"] == "MAR" and rep.loc["uf", "depende_de"] == "primeiro_aparelho"
    assert rep.loc["telefone", "mecanismo"] == "compatível com MCAR"


def test_imputa_regiao_pela_moda_das_sessoes():
    c = pd.DataFrame({"conta_id": [1, 2], "regiao": pd.array([None, "Sul"], dtype="string")})
    s = pd.DataFrame({"conta_id": [1, 1, 1], "regiao": ["Norte", "Norte", "Sul"]})
    out, f = nulls.impute_region(c, s)
    assert out.loc[0, "regiao"] == "Norte" and out.loc[0, "regiao_imputada"] and not out.loc[1, "regiao_imputada"]


# ------------------------------------------------------------------ outliers
def _pdays():
    rng = np.random.default_rng(1)
    h = rng.gamma(2, 0.7, 2000)
    h[0] = 30
    return pd.DataFrame({"horas": h, "mes": "2024-05"})


def test_iqr_e_mad_marcam_extremo_e_nao_o_tipico():
    p = _pdays()
    for flags in (outliers.iqr_flags(p, 3.0), outliers.mad_flags(p, 3.5)):
        assert flags.iloc[0] and flags.mean() < 0.05


def test_sazonal_marca_pico_e_ignora_fim_de_semana():
    idx = pd.date_range("2024-01-01", "2024-06-30")
    y = pd.Series(1000 + 300 * (idx.dayofweek >= 5), index=idx, dtype=float)
    y[pd.Timestamp("2024-04-10")] *= 2.5
    out = outliers.seasonal_flags(y, 28, 4.0)
    assert out.loc["2024-04-10", "anomalo"] and out["anomalo"].sum() == 1


def test_isolation_forest_explica_robo():
    rng = np.random.default_rng(2)
    n = 400
    f = pd.DataFrame({"reproducoes_por_dia": rng.gamma(2, 1.5, n), "horas_por_dia": rng.gamma(2, 0.8, n),
                      "frac_curtas": rng.beta(1, 9, n), "frac_madrugada": rng.beta(1, 12, n), "entropia_hora": rng.normal(1.5, .3, n),
                      "dispositivos": rng.integers(1, 4, n), "regioes": rng.integers(1, 2, n), "telas_simultaneas": rng.integers(1, 3, n),
                      "telas_acima_do_limite": 0.0}, index=pd.MultiIndex.from_arrays([range(n), ["2024-05"] * n]))
    f.iloc[0] = [60, 1.5, 0.95, 0.25, 3.1, 1, 0, 1, 0]
    out = outliers.isolation_forest(f, 0.01, 7)
    assert out.iloc[0]["explicacao"] == "robô" and out["anomalo"].mean() < 0.05


# ------------------------------------------------------------------ quarentena
def test_orfaos_vao_para_quarentena_e_validos_ficam():
    t = {"pagamentos": pd.DataFrame({"pagamento_id": [1, 2, 3], "fatura_id": pd.array([10, 99, None], dtype="Int64")}),
         "faturas": pd.DataFrame({"fatura_id": [10]}), "perfis": pd.DataFrame({"perfil_id": [5]}),
         "sessoes_app": pd.DataFrame({"sessao_id": [1, 2], "perfil_id": [5, 6]}),
         "reproducoes": pd.DataFrame({"reproducao_id": [1, 2], "perfil_id": [5, 5], "sessao_id": pd.array([1, 77], dtype="Int64")})}
    t, q, f = quarantine.referential(t)
    assert set(zip(q["tabela"], q["chave"])) == {("pagamentos", 2), ("sessoes_app", 2)}
    assert set(t["pagamentos"]["pagamento_id"]) == {1, 3}          # pagamento sem fatura (nulo) não é órfão
    assert ("sessao_nao_recebida", 2) in set(zip(f["regra"], f["chave"]))
