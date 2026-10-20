"""Precisão e recall de cada técnica contra o registro de defeitos.

Papel: para cada técnica, contar o que ela marcou e cruzar com o registro:
       - acerto: marcou um defeito injetado;
       - legítimo derrubado: marcou um outlier verdadeiro (custo de negócio);
       - nativo: marcou algo que já existia na base de referência (achado real, não erro da técnica);
       - falso positivo: o resto.
       precisão = acertos / (acertos + falsos positivos + legítimos derrubados)
       recall   = acertos / defeitos que a técnica deveria pegar
Entrada: data/defect_log, flags e staging das execuções limpa e verdade.
Saída: DataFrame com uma linha por técnica.
Dependências: pandas, dq.clean (para rodar os detectores isoladamente), dq.corrupt.log (formato).

Este é um dos dois únicos lugares (com src/dq/corrupt) que leem o registro de defeitos.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dq.clean import outliers, timestamps, usage_limits
from dq.config import load_yaml, settings
from dq.domain import plan_screens
from dq.io import read_table

USAGE_INFLATING = {"sessao_absurda", "tempo_maior_que_conteudo", "replay_lote"}


def load_defect_log() -> pd.DataFrame:
    return pd.read_parquet(settings()["paths"]["defect_log"] / "defect_log.parquet")


def score(name: str, unidade: str, flagged: set, positives: set, legit: set, native: set,
          ignore: set | None = None, grupo: str = "") -> dict:
    ignore = ignore or set()
    flagged = flagged - ignore
    positives = positives - ignore
    tp = flagged & positives
    leg = (flagged & legit) - positives
    nat = (flagged & native) - positives - legit
    fp = flagged - tp - leg - nat
    denom = len(tp) + len(fp) + len(leg)
    return {"tecnica": name, "grupo": grupo, "unidade": unidade, "marcados": len(flagged), "acertos": len(tp),
            "falsos_positivos": len(fp), "legitimos_derrubados": len(leg), "nativos": len(nat),
            "defeitos_alvo": len(positives), "precisao": len(tp) / denom if denom else float("nan"),
            "recall": len(tp) / len(positives) if positives else float("nan")}


def _keys(df: pd.DataFrame, tables: list[str] | None = None) -> set:
    d = df if tables is None else df[df["tabela"].isin(tables)]
    return set(zip(d["tabela"], d["chave"].astype("int64")))


def _flags(run: str) -> pd.DataFrame:
    from dq.evaluate.variants import run_dir
    return pd.read_parquet(run_dir(run) / "flags.parquet")


# ------------------------------------------------------------------------------ regras por linha
RULES = [
    # nome, regras no flags, tipos no registro, tabelas avaliadas, grupo
    ("Regras de cadastro (contas internas)", ["conta_interna"], ["conta_teste"], ["contas"], "cadastro"),
    ("Integridade referencial (quarentena)", ["orfao"], ["orfao"], ["pagamentos", "sessoes_app", "reproducoes"], "cadastro"),
    ("Chave idempotente + janela (pagamentos)", ["pagamento_duplicado"], ["webhook_duplicado", "retentativa_duplicada"], ["pagamentos"], "cobranca"),
    ("SCD2: preço vigente na data", ["preco_divergente"], ["preco_divergente"], ["faturas"], "cobranca"),
    ("Máquina de estados (ordem dos eventos)", ["evento_fora_de_ordem"], ["evento_fora_de_ordem"], ["assinatura_eventos"], "assinatura"),
    ("Intervalos por conta (sobreposição)", ["assinatura_sobreposta"], ["assinatura_sobreposta"], ["assinaturas"], "assinatura"),
    ("Chave natural (replay de lote)", ["uso_duplicado"], ["replay_lote"], ["sessoes_app", "reproducoes"], "uso"),
    ("Contrato de formato (fuso misturado)", ["fuso_misturado"], ["fuso_misturado"], ["sessoes_app", "reproducoes"], "uso"),
    ("Desvio por aparelho (relógio errado)", ["relogio_errado", "relogio_zerado"], ["relogio_errado"], ["sessoes_app", "reproducoes"], "uso"),
    ("Sequência sem sobreposição (troca de ID)", ["dispositivo_unificado"], ["troca_dispositivo"], ["dispositivos"], "uso"),
    ("Regra física (por reprodução)", ["tempo_negativo", "tempo_negativo_sem_horario", "tempo_maior_que_conteudo", "mais_de_24h_por_aparelho"],
     ["tempo_negativo", "tempo_maior_que_conteudo", "sessao_absurda"], ["reproducoes"], "uso"),
]


def evaluate_rules(log: pd.DataFrame, ignore: set) -> list[dict]:
    """Regras por linha, a partir das marcações das execuções limpa e verdade. As linhas de contas
    clonadas (teste/robô) são avaliadas no nível da conta, não linha a linha (`ignore`)."""
    lim, ver = _flags("limpa"), _flags("verdade")
    defects = log[log["categoria"] == "defeito"]
    legit = _keys(log[log["categoria"] != "defeito"])
    rows = []
    for name, regras, tipos, tabelas, grupo in RULES:
        f = lim[lim["regra"].isin(regras) & lim["tabela"].isin(tabelas)]
        n = ver[ver["regra"].isin(regras) & ver["tabela"].isin(tabelas)]
        pos = _keys(defects[defects["tipo"].isin(tipos)], tabelas)
        other = _keys(defects[~defects["tipo"].isin(tipos)], tabelas) - pos   # defeito de outro tipo: não é falso positivo
        rows.append(score(name, "linha", _keys(f), pos, legit, _keys(n), ignore | other, grupo))
    return rows


# ------------------------------------------------------------------------------ estatísticos
COLS = {
    "reproducoes": ["reproducao_id", "perfil_id", "conta_id", "sessao_id", "dispositivo_id", "titulo_id", "episodio_id",
                    "inicio_em", "fim_em", "segundos_assistidos", "duracao_conteudo_seg"],
    "sessoes_app": ["sessao_id", "conta_id", "dispositivo_id", "inicio_em", "regiao"],
    "contas": ["conta_id", "uf"], "planos": None, "assinaturas": ["conta_id", "plano_id", "iniciada_em"],
    "episodios": ["episodio_id", "titulo_id", "temporada", "disponivel_desde"],
}
EPOCH = pd.Timestamp("1970-01-01")


def pd_key(perfil: pd.Series, day: pd.Series) -> np.ndarray:
    """Chave inteira de perfil-dia (perfil · 10⁵ + dia desde 1970): bem mais leve que tuplas."""
    return perfil.to_numpy(dtype="int64") * 100_000 + ((day - EPOCH).dt.days.to_numpy(dtype="int64"))


def _load(run: str) -> dict[str, pd.DataFrame]:
    from dq.evaluate.variants import run_dir

    return {n: read_table(run_dir(run) / "staging", n, columns=c) for n, c in COLS.items()}


def stat_sets(run: str, ccfg: dict, keep_maps: bool = False, clones: set | None = None) -> dict:
    """Roda IQR, z robusto, regra física, séries diárias e Isolation Forest numa base (staging) e
    devolve só os conjuntos marcados. Uma base por vez, para caber na memória."""
    st = _load(run)
    tz = timestamps.account_tz(st["contas"])
    r = st["reproducoes"].dropna(subset=["conta_id"])
    oc = ccfg["outliers"]
    out: dict = {}
    pdays = outliers.perfil_day(r, tz)
    key = pd_key(pdays["perfil_id"], pdays["dia"])
    phys = outliers.physical_flags(r, usage_limits.physical_violations(r, ccfg["limites"]), tz)
    out["perfil_dia"] = {
        "IQR por mês (Q3 + 3·IQR)": set(key[outliers.iqr_flags(pdays, oc["iqr_k"]).to_numpy()]),
        "Z-score robusto (mediana/MAD)": set(key[outliers.mad_flags(pdays, oc["mad_z"]).to_numpy()]),
        "Regra física (≤ duração, ≤ 24 h/aparelho)": set(pd_key(phys["perfil_id"], phys["dia"])),
    }
    daily = outliers.daily_series(pdays)
    del pdays
    seas = outliers.seasonal_flags(daily, oc["sazonal_janela_dias"], oc["sazonal_z"])
    loc = outliers.local_time(r["inicio_em"], r["conta_id"], tz)
    expl = outliers.explain_days(seas, r[["titulo_id"]].assign(inicio_em=loc), st["episodios"])
    out["dia"] = {
        "Z-score no total diário (sem sazonalidade)": set(daily.index[outliers.naive_daily_flags(daily, oc["sazonal_z"]).to_numpy()]),
        "Sazonal (tendência + dia da semana)": set(seas.index[seas["anomalo"] & (seas["z"] > 0)]),
        "Sazonal + calendário de estreias e feriados": set(expl.index[expl["explicacao"] == "erro provável"]),
    }
    if keep_maps:
        allr = st["reproducoes"]
        aloc = outliers.local_time(allr["inicio_em"], allr["conta_id"], tz).dt.floor("D")
        out["map_pd"] = pd.Series(pd_key(allr["perfil_id"], aloc), index=allr["reproducao_id"].to_numpy())
        out["map_dia"] = pd.Series(aloc.to_numpy(), index=allr["reproducao_id"].to_numpy())
        clones = clones or set()
        out["clone_rows"] = {("reproducoes", k) for k in allr.loc[allr["conta_id"].isin(clones), "reproducao_id"]} | \
            {("sessoes_app", k) for k in st["sessoes_app"].loc[st["sessoes_app"]["conta_id"].isin(clones), "sessao_id"]}
        out["clone_pd"] = set(out["map_pd"][allr["conta_id"].isin(clones).to_numpy()])
    s = st["sessoes_app"].dropna(subset=["conta_id"])
    screens = st["assinaturas"].sort_values("iniciada_em").drop_duplicates("conta_id", keep="last") \
        .set_index("conta_id")["plano_id"].map(plan_screens(st["planos"]))
    feat = outliers.account_features(r, s, tz, screens)
    iso = outliers.isolation_forest(feat, oc["if_contaminacao"], oc["if_seed"])
    c = lambda m: set(iso.index[m].get_level_values(0))  # noqa: E731
    out["conta"] = {
        "Isolation Forest (qualquer anomalia)": c(iso["anomalo"]),
        "Isolation Forest + explicação (robô / telas)": c(iso["explicacao"].isin(["robô", "compartilhamento acima do limite"])),
        "Regra simples: telas acima do limite": c(feat["telas_acima_do_limite"] > 0),
        "Regra simples: > 15 reproduções curtas/dia": c((feat["reproducoes_por_dia"] > 15) & (feat["frac_curtas"] > 0.6)),
    }
    return out


def evaluate_statistical(log: pd.DataFrame, dirty: dict, ref: dict) -> list[dict]:
    lr = log[log["tabela"] == "reproducoes"]
    by_pd, by_day = dirty["map_pd"], dirty["map_dia"]

    def pdset(mask) -> set:
        return set(by_pd.reindex(lr.loc[mask, "chave"]).dropna().astype("int64"))

    rows = []
    # perfil-dia: alvo = defeitos que inflam horas; outros defeitos de uso ficam fora da conta
    pos = pdset((lr["categoria"] == "defeito") & lr["tipo"].isin(USAGE_INFLATING))
    other = pdset((lr["categoria"] == "defeito") & ~lr["tipo"].isin(USAGE_INFLATING | {"atrasado", "conta_teste"}))
    legit = pdset(lr["categoria"] == "legitimo")
    ignore = dirty["clone_pd"] | (other - pos)
    rows += [score(k, "perfil-dia", v, pos, legit, ref["perfil_dia"][k], ignore, "outlier de uso")
             for k, v in dirty["perfil_dia"].items()]
    # dia da plataforma: alvo = dias de replay; legítimo = estreias e feriados
    day = by_day.reindex(lr["chave"]).to_numpy()
    lrd = lr.assign(dia=day)
    # um lote diário em UTC cai em dois dias locais; o dia-alvo de cada lote é o dia local que o concentra
    def main_days(tipo: str) -> set:
        g = lrd[lrd["tipo"] == tipo].dropna(subset=["dia"])
        return set(g.groupby("data")["dia"].agg(lambda x: x.value_counts().index[0])) if len(g) else set()

    pos_d = main_days("replay_lote")
    leg_d = main_days("maratona_lancamento") | main_days("pico_feriado")
    rows += [score(k, "dia", v, pos_d, leg_d, ref["dia"][k], None, "série diária") for k, v in dirty["dia"].items()]
    # conta: alvo = robôs e compartilhamento acima do limite
    pos_c = set(log.loc[log["tipo"].isin(["bot", "compartilhamento_excedente"]) & (log["tabela"] == "contas"), "chave"])
    # no nível da conta, legítimo é o PADRÃO raro e real: compartilhamento pago e usuário intenso
    leg_c = set(log.loc[log["tipo"].isin(["compartilhamento_legitimo", "usuario_intenso"]), "conta_id"].dropna().astype(int))
    clones = set(log.loc[log["tipo"] == "conta_teste", "chave"])
    rows += [score(k, "conta", v, pos_c, leg_c, ref["conta"][k], clones, "padrão por conta") for k, v in dirty["conta"].items()]
    return rows


def evaluate_imputation(log: pd.DataFrame) -> dict:
    """Acerto da região imputada (UF nula da TV) contra a UF original do registro."""
    from dq.domain import UF_REGION, normalize_uf
    from dq.evaluate.variants import run_dir

    c = read_table(run_dir("limpa") / "clean", "contas")
    lg = log[log["tipo"] == "nulo_uf_tv"]
    truth = pd.Series(normalize_uf(lg["valor_original"]).map(UF_REGION).to_numpy(), index=lg["chave"].to_numpy())
    got = c.set_index("conta_id").reindex(truth.index)
    imputed = got["regiao_imputada"].fillna(False).astype(bool)
    hit = (got.loc[imputed, "regiao"] == truth[imputed])
    return {"nulos_injetados": len(truth), "imputados": int(imputed.sum()), "cobertura": float(imputed.mean()),
            "acerto_regiao": float(hit.mean()) if len(hit) else float("nan")}


def evaluate_all() -> tuple[pd.DataFrame, dict]:
    import gc

    log = load_defect_log()
    ccfg = load_yaml("cleaning")
    clones = set(log.loc[log["tipo"].isin(["conta_teste", "bot"]), "chave"])
    dirty = stat_sets("limpa", ccfg, keep_maps=True, clones=clones)
    gc.collect()
    ref = stat_sets("verdade", ccfg)
    gc.collect()
    rows = evaluate_rules(log, dirty["clone_rows"]) + evaluate_statistical(log, dirty, ref)
    return pd.DataFrame(rows), evaluate_imputation(log)
