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


def clone_rows(log: pd.DataFrame, staging: dict[str, pd.DataFrame]) -> set:
    """Linhas de contas clonadas (teste/robô): avaliadas no nível da conta, não linha a linha."""
    contas = set(log.loc[log["tipo"].isin(["conta_teste", "bot"]), "chave"])
    out = set()
    for t, key in (("sessoes_app", "sessao_id"), ("reproducoes", "reproducao_id")):
        df = staging[t]
        out |= {(t, k) for k in df.loc[df["conta_id"].isin(contas), key]}
    return out


def evaluate_rules(log: pd.DataFrame, staging: dict[str, pd.DataFrame]) -> list[dict]:
    lim, ver = _flags("limpa"), _flags("verdade")
    defects = log[log["categoria"] == "defeito"]
    legit = _keys(log[log["categoria"] != "defeito"])
    ignore = clone_rows(log, staging)
    rows = []
    for name, regras, tipos, tabelas, grupo in RULES:
        f = lim[lim["regra"].isin(regras) & lim["tabela"].isin(tabelas)]
        n = ver[ver["regra"].isin(regras) & ver["tabela"].isin(tabelas)]
        pos = _keys(defects[defects["tipo"].isin(tipos)], tabelas)
        rows.append(score(name, "linha", _keys(f), pos, legit, _keys(n), ignore, grupo))
    return rows


# ------------------------------------------------------------------------------ estatísticos
def _tz(st: dict[str, pd.DataFrame]) -> pd.Series:
    return timestamps.account_tz(st["contas"])


def _pd_keys(r: pd.DataFrame, tz: pd.Series) -> pd.Series:
    loc = outliers.local_time(r["inicio_em"], r["conta_id"], tz).dt.floor("D")
    return pd.Series(list(zip(r["perfil_id"], loc)), index=r.index)


def _perfil_day_sets(st: dict[str, pd.DataFrame], ccfg: dict) -> dict[str, set]:
    r = st["reproducoes"].dropna(subset=["conta_id"])
    tz = _tz(st)
    pdays = outliers.perfil_day(r, tz)
    key = pd.Series(list(zip(pdays["perfil_id"], pdays["dia"])))
    oc = ccfg["outliers"]
    phys = outliers.physical_flags(r, usage_limits.physical_violations(r, ccfg["limites"]), tz)
    return {
        "IQR por mês (Q3 + 3·IQR)": set(key[outliers.iqr_flags(pdays, oc["iqr_k"]).to_numpy()]),
        "Z-score robusto (mediana/MAD)": set(key[outliers.mad_flags(pdays, oc["mad_z"]).to_numpy()]),
        "Regra física (≤ duração, ≤ 24 h/aparelho)": set(zip(phys["perfil_id"], phys["dia"])),
    }


def evaluate_usage_outliers(log: pd.DataFrame, st: dict[str, pd.DataFrame], st_ref: dict[str, pd.DataFrame]) -> list[dict]:
    ccfg = load_yaml("cleaning")
    r = st["reproducoes"]
    tz = _tz(st)
    pk = _pd_keys(r, tz)
    ids = r["reproducao_id"]
    by_id = pd.Series(pk.to_numpy(), index=ids.to_numpy())
    lr = log[log["tabela"] == "reproducoes"]

    def pdset(mask) -> set:
        return set(by_id.reindex(lr.loc[mask, "chave"]).dropna())

    positives = pdset((lr["categoria"] == "defeito") & lr["tipo"].isin(USAGE_INFLATING))
    other = pdset((lr["categoria"] == "defeito") & ~lr["tipo"].isin(USAGE_INFLATING | {"atrasado", "conta_teste"}))
    legit = pdset(lr["categoria"] == "legitimo")
    clones = set(log.loc[log["tipo"] == "conta_teste", "chave"])
    ignore = set(pk[r["conta_id"].isin(clones).to_numpy()]) | (other - positives)
    dirty = _perfil_day_sets(st, ccfg)
    ref = _perfil_day_sets(st_ref, ccfg)
    return [score(k, "perfil-dia", v, positives, legit, ref[k], ignore, "outlier de uso") for k, v in dirty.items()]


def _day_sets(st: dict[str, pd.DataFrame], ccfg: dict) -> dict[str, set]:
    r = st["reproducoes"].dropna(subset=["conta_id"])
    tz = _tz(st)
    pdays = outliers.perfil_day(r, tz)
    daily = outliers.daily_series(pdays)
    oc = ccfg["outliers"]
    seas = outliers.seasonal_flags(daily, oc["sazonal_janela_dias"], oc["sazonal_z"])
    expl = outliers.explain_days(seas, r.assign(inicio_em=outliers.local_time(r["inicio_em"], r["conta_id"], tz)), st["episodios"])
    return {
        "Z-score no total diário (sem sazonalidade)": set(daily.index[outliers.naive_daily_flags(daily, oc["sazonal_z"]).to_numpy()]),
        "Sazonal (tendência + dia da semana)": set(seas.index[seas["anomalo"] & (seas["z"] > 0)]),
        "Sazonal + calendário de estreias e feriados": set(expl.index[expl["explicacao"] == "erro provável"]),
    }


def evaluate_daily(log: pd.DataFrame, st: dict[str, pd.DataFrame], st_ref: dict[str, pd.DataFrame]) -> list[dict]:
    ccfg = load_yaml("cleaning")
    r = st["reproducoes"]
    day = pd.Series(_pd_keys(r, _tz(st)).str[1].to_numpy(), index=r["reproducao_id"].to_numpy())
    lr = log[log["tabela"] == "reproducoes"].copy()
    lr["dia"] = day.reindex(lr["chave"]).to_numpy()
    pos = set(lr.loc[lr["tipo"] == "replay_lote", "dia"].value_counts().loc[lambda x: x > 50].index)
    legit = set(lr.loc[lr["tipo"].isin(["maratona_lancamento", "pico_feriado"]), "dia"].value_counts().loc[lambda x: x > 50].index)
    dirty, ref = _day_sets(st, ccfg), _day_sets(st_ref, ccfg)
    return [score(k, "dia", v, pos, legit, ref[k], None, "série diária") for k, v in dirty.items()]


def _account_sets(st: dict[str, pd.DataFrame], ccfg: dict) -> dict[str, set]:
    r = st["reproducoes"].dropna(subset=["conta_id"])
    s = st["sessoes_app"].dropna(subset=["conta_id"])
    tz = _tz(st)
    screens = st["assinaturas"].sort_values("iniciada_em").drop_duplicates("conta_id", keep="last").set_index("conta_id")["plano_id"].map(plan_screens(st["planos"]))
    feat = outliers.account_features(r, s, tz, screens)
    oc = ccfg["outliers"]
    iso = outliers.isolation_forest(feat, oc["if_contaminacao"], oc["if_seed"])
    c = lambda m: set(iso.index[m].get_level_values(0))  # noqa: E731
    return {
        "Isolation Forest (qualquer anomalia)": c(iso["anomalo"]),
        "Isolation Forest + explicação (robô / telas)": c(iso["explicacao"].isin(["robô", "compartilhamento acima do limite"])),
        "Regra simples: telas acima do limite": c(feat["telas_acima_do_limite"] > 0),
        "Regra simples: > 15 reproduções curtas/dia": c((feat["reproducoes_por_dia"] > 15) & (feat["frac_curtas"] > 0.6)),
    }


def evaluate_accounts(log: pd.DataFrame, st: dict[str, pd.DataFrame], st_ref: dict[str, pd.DataFrame]) -> list[dict]:
    ccfg = load_yaml("cleaning")
    pos = set(log.loc[log["tipo"].isin(["bot", "compartilhamento_excedente"]) & (log["tabela"] == "contas"), "chave"])
    legit = set(log.loc[(log["categoria"] == "legitimo"), "conta_id"].dropna().astype(int))
    clones = set(log.loc[log["tipo"] == "conta_teste", "chave"])
    dirty, ref = _account_sets(st, ccfg), _account_sets(st_ref, ccfg)
    return [score(k, "conta", v, pos, legit, ref[k], clones, "padrão por conta") for k, v in dirty.items()]


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
    from dq.evaluate.variants import run_dir

    log = load_defect_log()
    names = ["contas", "planos", "assinaturas", "episodios", "sessoes_app", "reproducoes"]
    st = {n: read_table(run_dir("limpa") / "staging", n) for n in names}
    st_ref = {n: read_table(run_dir("verdade") / "staging", n) for n in names}
    rows = evaluate_rules(log, st) + evaluate_usage_outliers(log, st, st_ref) + evaluate_daily(log, st, st_ref) \
        + evaluate_accounts(log, st, st_ref)
    return pd.DataFrame(rows), evaluate_imputation(log)
