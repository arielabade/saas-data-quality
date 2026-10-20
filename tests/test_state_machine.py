"""Máquina de estados da assinatura: todas as transições válidas, as inválidas, correção de ordem e churn."""

from __future__ import annotations

import pandas as pd
import pytest

from dq.state import churn, machine

T = pd.Timestamp
STATES = [None, "trial", "ativo", "inadimplente", "cancelamento_agendado", "cancelado"]
EVENTS = ["assinatura_criada", "trial_iniciado", "trial_convertido", "upgrade", "downgrade", "metodo_pagamento_alterado",
          "inadimplencia_iniciada", "inadimplencia_resolvida", "cancelamento_solicitado", "encerrada", "reativada",
          "membro_extra_adicionado", "membro_extra_removido"]

EXPECTED = {
    (None, "assinatura_criada"): "ativo",
    ("ativo", "trial_iniciado"): "trial", ("ativo", "reativada"): "ativo",
    ("ativo", "inadimplencia_iniciada"): "inadimplente", ("ativo", "cancelamento_solicitado"): "cancelamento_agendado",
    ("ativo", "encerrada"): "cancelado",
    ("trial", "trial_convertido"): "ativo", ("trial", "inadimplencia_iniciada"): "inadimplente",
    ("trial", "cancelamento_solicitado"): "cancelamento_agendado", ("trial", "encerrada"): "cancelado",
    ("inadimplente", "inadimplencia_resolvida"): "ativo", ("inadimplente", "inadimplencia_iniciada"): "inadimplente",
    ("inadimplente", "cancelamento_solicitado"): "cancelamento_agendado", ("inadimplente", "encerrada"): "cancelado",
    ("cancelamento_agendado", "encerrada"): "cancelado",
    ("cancelamento_agendado", "inadimplencia_iniciada"): "cancelamento_agendado",
    ("cancelamento_agendado", "inadimplencia_resolvida"): "cancelamento_agendado",
}
for s in ("ativo", "trial", "inadimplente", "cancelamento_agendado"):
    for e in machine.NEUTRAL:
        EXPECTED[(s, e)] = s


@pytest.mark.parametrize("state,event", [(s, e) for s in STATES for e in EVENTS])
def test_toda_combinacao_de_estado_e_evento(state, event):
    """Cobre as 78 combinações: as válidas levam ao estado esperado; as demais são inválidas (None)."""
    assert machine.step(state, event) == EXPECTED.get((state, event))


def test_nada_sai_de_cancelado():
    assert all(machine.step("cancelado", e) is None for e in EVENTS)


def _sub(**kw):
    d = dict(assinatura_id=[1], conta_id=[10], plano_id=[2], periodicidade=["mensal"], iniciada_em=[T("2024-01-10")],
             cancelamento_solicitado_em=[T("2024-04-01")], encerrada_em=[T("2024-04-10")], assinatura_anterior_id=pd.array([None], dtype="Int64"))
    d.update(kw)
    return pd.DataFrame(d)


def _ev(rows):
    df = pd.DataFrame(rows, columns=["evento_id", "tipo", "ocorrido_em"])
    df["assinatura_id"] = 1
    df["plano_anterior_id"] = pd.array([None] * len(df), dtype="Int64")
    df["plano_novo_id"] = pd.array([None] * len(df), dtype="Int64")
    return df


def test_desvio_de_minutos_e_corrigido_para_a_criacao():
    ev = _ev([(1, "assinatura_criada", T("2024-01-10 12:00")), (2, "inadimplencia_iniciada", T("2024-01-10 11:58"))])
    out, f = machine.fix_event_order(ev, _sub(), 24)
    assert out.set_index("evento_id").loc[2, "ocorrido_em"] == T("2024-01-10 12:00")
    assert f["regra"].tolist() == ["evento_desvio_relogio"]


def test_encerramento_antes_da_criacao_e_corrigido_pelo_cabecalho():
    ev = _ev([(1, "assinatura_criada", T("2024-01-10")), (2, "cancelamento_solicitado", T("2024-04-01")),
              (3, "encerrada", T("2023-11-01"))])
    out, f = machine.fix_event_order(ev, _sub(), 24)
    assert out.set_index("evento_id").loc[3, "ocorrido_em"] == T("2024-04-10")
    tl, _ = machine.build_timeline(out, _sub())
    assert tl["estado"].tolist() == ["ativo", "cancelamento_agendado"] and tl["fim"].iloc[-1] == T("2024-04-10")


def test_sem_cabecalho_o_evento_impossivel_vai_para_quarentena():
    ev = _ev([(1, "assinatura_criada", T("2024-01-10")), (3, "encerrada", T("2023-11-01"))])
    out, f = machine.fix_event_order(ev, _sub(encerrada_em=[pd.NaT]), 24)
    assert 3 not in set(out["evento_id"]) and "quarentena" in set(f["acao"])


def test_pipeline_ingenuo_reabre_assinatura_encerrada():
    ev = _ev([(1, "assinatura_criada", T("2024-01-10")), (3, "encerrada", T("2023-11-01"))])
    tl, _ = machine.build_timeline(ev, _sub(), strict=False)
    assert tl["fim"].iloc[-1] == machine.END_OF_DATA       # nunca churna


def test_transicao_invalida_e_ignorada_e_sinalizada():
    ev = _ev([(1, "assinatura_criada", T("2024-01-10")), (2, "trial_convertido", T("2024-01-20")),
              (3, "encerrada", T("2024-02-10")), (4, "inadimplencia_resolvida", T("2024-03-01"))])
    tl, f = machine.build_timeline(ev, _sub())
    assert f["chave"].tolist() == [2, 4]                 # convertido sem trial; evento depois de encerrada
    assert tl["estado"].tolist() == ["ativo"] and tl["fim"].iloc[0] == T("2024-02-10")


def test_upgrade_muda_o_plano_no_intervalo():
    ev = _ev([(1, "assinatura_criada", T("2024-01-10")), (2, "upgrade", T("2024-02-10"))])
    ev.loc[1, ["plano_anterior_id", "plano_novo_id"]] = [1, 3]
    tl, _ = machine.build_timeline(ev, _sub())
    assert tl["plano_id"].tolist() == [1, 3]


def test_sobreposicao_sem_vinculo_vai_para_quarentena_reativacao_nao():
    tl = pd.DataFrame({"assinatura_id": [1, 2, 3], "conta_id": [10, 10, 10], "estado": "ativo",
                       "inicio": [T("2024-01-01"), T("2024-03-01"), T("2024-12-30")],
                       "fim": [T("2024-12-31"), machine.END_OF_DATA, machine.END_OF_DATA],
                       "assinatura_anterior_id": pd.array([None, None, 1], dtype="Int64")})
    ids, f = machine.resolve_overlaps(tl, ["ativo"])
    assert set(ids) == {2}


def test_churn_com_carencia_e_tipos():
    tl = pd.DataFrame({"assinatura_id": [1, 1, 2, 3], "conta_id": [10, 10, 10, 20],
                       "estado": ["ativo", "cancelamento_agendado", "ativo", "inadimplente"],
                       "inicio": [T("2024-01-01"), T("2024-03-01"), T("2024-03-15"), T("2024-01-01")],
                       "fim": [T("2024-03-01"), T("2024-03-10"), machine.END_OF_DATA, T("2024-05-01")]})
    vig = ["ativo", "inadimplente", "cancelamento_agendado"]
    sp = churn.account_spans(tl, vig, 3)                     # voltou 5 dias depois: com 3 de carência, é churn
    s10 = sp[sp["conta_id"] == 10]
    assert len(s10) == 2 and s10["tipo_churn"].iloc[0] == "voluntario" and not s10["churn"].iloc[1]
    assert sp[sp["conta_id"] == 20]["tipo_churn"].iloc[0] == "involuntario"
    sp7 = churn.account_spans(tl, vig, 7)                    # com 7 dias de carência, não é churn
    assert len(sp7[sp7["conta_id"] == 10]) == 1 and not sp7[sp7["conta_id"] == 10]["churn"].iloc[0]
