"""Impacto da limpeza nas métricas de negócio.

Papel: comparar os marts de cada variante com a verdade (base sem defeitos, mesmo pipeline):
       MRR, assinantes ativos, churn mensal, receita por plano, horas por assinante e retenção
       por coorte; e medir quanto da base estava suja.
Entrada: data/runs/*/marts, data/raw, data/defect_log.
Saída: tabelas de série mensal por variante e de erro contra a verdade.
Dependências: pandas, numpy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dq.evaluate.variants import run_dir

METRICS = {
    # chave: (mart, coluna, rótulo, tipo de erro)
    "mrr": ("mrr", "mrr_centavos", "MRR", "pct"),
    "ativos": ("assinantes", "ativos_fim", "Assinantes ativos", "pct"),
    "churn": ("assinantes", "taxa_churn", "Churn mensal", "pp"),
    "horas": ("engajamento", "horas_por_assinante", "Horas por assinante", "pct"),
    "mrr_basico": ("mrr", "mrr_basico_centavos", "MRR Básico", "pct"),
    "mrr_padrao": ("mrr", "mrr_padrao_centavos", "MRR Padrão", "pct"),
    "mrr_premium": ("mrr", "mrr_premium_centavos", "MRR Premium", "pct"),
}
SINCE = "2024-01"   # os 3 primeiros meses têm base pequena demais para erro relativo estável


def load_marts(variant: str) -> dict[str, pd.DataFrame]:
    d = run_dir(variant) / "marts"
    return {m: pd.read_parquet(d / f"{m}.parquet") for m in ("mrr", "assinantes", "engajamento", "coortes")}


def long_series(variants: list[str]) -> pd.DataFrame:
    rows = []
    for v in variants:
        m = load_marts(v)
        for key, (mart, col, label, _) in METRICS.items():
            df = m[mart][["mes", col]].rename(columns={col: "valor"})
            df["variante"], df["metrica"], df["rotulo"] = v, key, label
            rows.append(df)
    return pd.concat(rows, ignore_index=True)


def errors(long: pd.DataFrame, truth: str = "verdade") -> pd.DataFrame:
    """Erro médio contra a verdade desde SINCE. Percentual para níveis; pontos percentuais para taxas."""
    t = long[long["variante"] == truth].set_index(["metrica", "mes"])["valor"]
    out = []
    for (v, k), g in long[long["mes"] >= SINCE].groupby(["variante", "metrica"]):
        g = g.set_index("mes")["valor"]
        tv = t.loc[k].reindex(g.index)
        kind = METRICS[k][3]
        if kind == "pct":
            e = 100 * (g - tv) / tv.replace(0, np.nan)
        else:
            e = 100 * (g - tv)
        out.append({"variante": v, "metrica": k, "rotulo": METRICS[k][2], "unidade": "%" if kind == "pct" else "p.p.",
                    "erro_medio": float(e.mean()), "erro_absoluto_medio": float(e.abs().mean()),
                    "erro_ultimo_mes": float(e.iloc[-1]), "pior_mes": str(e.abs().idxmax()) if e.notna().any() else "",
                    "erro_pior_mes": float(e.loc[e.abs().idxmax()]) if e.notna().any() else np.nan})
    return pd.DataFrame(out)


def cohort_summary(variants: list[str], ks: tuple[int, ...] = (3, 6, 12)) -> pd.DataFrame:
    rows = []
    for v in variants:
        c = load_marts(v)["coortes"]
        full = c.groupby("coorte")["k"].max()
        for k in ks:
            ok = full[full >= k].index
            g = c[(c["k"] == k) & c["coorte"].isin(ok)]
            rows.append({"variante": v, "k": k, "retencao_media": float(g["retidos"].sum() / g["base"].sum()) if len(g) else np.nan})
    return pd.DataFrame(rows)


def dirty_share(log: pd.DataFrame, raw_counts: dict[str, int]) -> pd.DataFrame:
    """Quanto de cada tabela foi tocado por defeito (linhas únicas com ao menos um defeito)."""
    d = log[log["categoria"] == "defeito"]
    rows = []
    for t, n in raw_counts.items():
        k = d.loc[d["tabela"] == t, "chave"].nunique()
        rows.append({"tabela": t, "linhas_raw": n, "linhas_com_defeito": int(k), "pct": 100 * k / n if n else 0.0,
                     "tipos": ", ".join(sorted(d.loc[d["tabela"] == t, "tipo"].unique()))})
    return pd.DataFrame(rows).sort_values("pct", ascending=False)
