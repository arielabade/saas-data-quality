"""Como os defeitos mudariam um modelo de churn.

Papel: montar as mesmas features de churn a partir de cada variante (verdade, limpa, ingênua),
       com o MESMO rótulo (churn real em 90 dias, da verdade), e mostrar quais features ficam
       enviesadas sem limpeza e quanto o modelo perde.
Entrada: data/runs/<variante>/{clean,warehouse}.
Saída: viés por feature (média da variante vs verdade), coeficientes e AUC fora do tempo.
Dependências: pandas, numpy, scikit-learn.

Desenho: população e rótulo vêm da verdade, para isolar o efeito da qualidade nas FEATURES.
Treino em fotos trimestrais até set/2025; teste em dez/2025, mar/2026 e jun/2026, sempre
pontuado com features da verdade (o modelo treinado em dado sujo é usado no mundo real).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from dq.evaluate.variants import run_dir
from dq.io import read_table
from dq.load.incremental import Warehouse

SNAPSHOTS = pd.date_range("2024-06-30", "2026-06-30", freq="QE")
TEST_FROM = pd.Timestamp("2025-12-31")
FEATURES = ["meses_de_casa", "falhas_pagamento_90d", "horas_30d", "dias_sem_uso", "aparelhos_90d", "reproducoes_30d"]
LABELS = {"meses_de_casa": "Meses de casa", "falhas_pagamento_90d": "Falhas de pagamento (90 d)",
          "horas_30d": "Horas assistidas (30 d)", "dias_sem_uso": "Dias sem uso", "aparelhos_90d": "Aparelhos (90 d)",
          "reproducoes_30d": "Reproduções (30 d)"}


def _inputs(variant: str) -> dict:
    d = run_dir(variant)
    r = Warehouse(d / "warehouse").read("reproducoes")[["conta_id", "dispositivo_id", "inicio_em", "segundos_assistidos"]]
    return {"plays": r.dropna(subset=["conta_id"]).astype({"conta_id": "int64"}),
            "pag": read_table(d / "clean", "pagamentos"), "spans": read_table(d / "clean", "periodos_conta")}


def features(inp: dict, contas: np.ndarray, t: pd.Timestamp) -> pd.DataFrame:
    r, pg, sp = inp["plays"], inp["pag"], inp["spans"]
    f = pd.DataFrame(index=pd.Index(contas, name="conta_id"))
    first = sp[sp["inicio"] <= t].groupby("conta_id")["inicio"].min()
    f["meses_de_casa"] = ((t - first.reindex(f.index)).dt.days / 30.4).fillna(0)
    fail = pg[(pg["status"] == "recusado") & (pg["processado_em"] > t - pd.Timedelta(days=90)) & (pg["processado_em"] <= t)]
    f["falhas_pagamento_90d"] = fail.groupby("conta_id").size().reindex(f.index).fillna(0)
    w30 = r[(r["inicio_em"] > t - pd.Timedelta(days=30)) & (r["inicio_em"] <= t)]
    w90 = r[(r["inicio_em"] > t - pd.Timedelta(days=90)) & (r["inicio_em"] <= t)]
    f["horas_30d"] = (w30.groupby("conta_id")["segundos_assistidos"].sum().clip(lower=0) / 3600).reindex(f.index).fillna(0)
    f["reproducoes_30d"] = w30.groupby("conta_id").size().reindex(f.index).fillna(0)
    f["aparelhos_90d"] = w90.groupby("conta_id")["dispositivo_id"].nunique().reindex(f.index).fillna(0)
    last = r[r["inicio_em"] <= t].groupby("conta_id")["inicio_em"].max()
    f["dias_sem_uso"] = ((t - last.reindex(f.index)).dt.days).fillna(120).clip(upper=120)
    return f


def build(variants: list[str]) -> dict[str, pd.DataFrame]:
    truth = _inputs("verdade")
    sp = truth["spans"]
    excluded = set(read_table(run_dir("verdade") / "clean", "contas_excluidas")["conta_id"])
    data = {v: [] for v in variants}
    inputs = {v: (truth if v == "verdade" else _inputs(v)) for v in variants}
    for t in SNAPSHOTS:
        alive = sp[(sp["inicio"] <= t) & (sp["fim"] > t)]
        alive = alive[~alive["conta_id"].isin(excluded)]
        y = (alive["churn"] & (alive["fim"] <= t + pd.Timedelta(days=90))).astype(int).to_numpy()
        contas = alive["conta_id"].to_numpy()
        for v in variants:
            f = features(inputs[v], contas, t)
            f["churn_90d"], f["foto"] = y, t
            data[v].append(f.reset_index())
    return {v: pd.concat(x, ignore_index=True) for v, x in data.items()}


def analyze(variants: tuple[str, ...] = ("verdade", "limpa", "ingenua")) -> dict:
    ds = build(list(variants))
    truth = ds["verdade"]
    bias, coefs, perf = [], [], []
    X0 = lambda df: np.log1p(df[FEATURES].clip(lower=0))  # noqa: E731
    tr0 = truth[truth["foto"] < TEST_FROM]
    ref_model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(X0(tr0), tr0["churn_90d"])
    for v, d in ds.items():
        for f in FEATURES:
            tm = truth[f].mean()
            bias.append({"variante": v, "feature": f, "rotulo": LABELS[f], "media": float(d[f].mean()),
                         "media_verdade": float(tm), "vies_pct": float(100 * (d[f].mean() - tm) / tm) if tm else np.nan,
                         "linhas_diferentes_pct": float(100 * (~np.isclose(d[f], truth[f], rtol=0.02, atol=0.01)).mean())})
        tr = d[d["foto"] < TEST_FROM]
        X = lambda df: np.log1p(df[FEATURES].clip(lower=0))  # noqa: E731
        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(X(tr), tr["churn_90d"])
        te = truth[truth["foto"] >= TEST_FROM]
        te_own = d[d["foto"] >= TEST_FROM]
        perf.append({"variante": v, "auc_teste_dados_reais": float(roc_auc_score(te["churn_90d"], model.predict_proba(X(te))[:, 1])),
                     "auc_teste_mesma_fonte": float(roc_auc_score(te_own["churn_90d"], model.predict_proba(X(te_own))[:, 1])),
                     "taxa_churn_90d": float(d["churn_90d"].mean()), "linhas_treino": len(tr),
                     # calibração: o modelo treinado em dado real aplicado às features desta variante
                     "churn_previsto_pelo_modelo_real": float(ref_model.predict_proba(X(te_own))[:, 1].mean()),
                     "churn_real_teste": float(te_own["churn_90d"].mean())})
        for f, c in zip(FEATURES, model[-1].coef_[0]):
            coefs.append({"variante": v, "feature": f, "rotulo": LABELS[f], "coeficiente": float(c)})
    return {"vies": pd.DataFrame(bias), "coeficientes": pd.DataFrame(coefs), "desempenho": pd.DataFrame(perf)}
