"""Marts de negócio: assinantes, MRR, churn, receita por plano, engajamento e coortes.

Papel: calcular as métricas exatamente como definidas em docs/METRICS.md, a partir da camada clean.
Entrada: linha do tempo (state.machine), spans por conta (state.churn), faturas e pagamentos
         limpos, uso do armazém e o conjunto de contas excluídas (internas, teste, robôs).
Saída: DataFrames mart_* (um por métrica) em centavos e horas.
Dependências: pandas, numpy.

Todas as funções recebem as tabelas já tratadas: o mart não limpa nada. Assim a variante
"ingênua" usa o MESMO código de mart, e a diferença entre variantes é só a limpeza.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MONTHS = pd.period_range("2023-10", "2026-10", freq="M")
PLAN_NAMES = {1: "basico", 2: "padrao", 3: "premium"}


def eom(p: pd.Period) -> pd.Timestamp:
    return p.to_timestamp(how="end").floor("s")


def at_instant(tl: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    return tl[(tl["inicio"] <= t) & (tl["fim"] > t)]


def invoice_cash(faturas: pd.DataFrame, pagamentos: pd.DataFrame) -> pd.Series:
    """Valor efetivamente recebido por fatura: cobranças aprovadas + reembolsos (negativos).
    Fatura marcada como paga sem nenhum pagamento (imperfeição nativa) usa o total da fatura."""
    pg = pagamentos[pagamentos["fatura_id"].notna()]
    ok = ((pg["tipo"] == "cobranca") & (pg["status"] == "aprovado")) | (pg["tipo"] == "reembolso")
    cash = pg[ok].groupby(pg.loc[ok, "fatura_id"].astype("int64"))["valor_centavos"].sum()
    out = faturas.set_index("fatura_id")["total_centavos"].astype(float) * np.nan
    out.loc[cash.index.intersection(out.index)] = cash
    paid_no_payment = (faturas.set_index("fatura_id")["status"] == "paga") & out.isna()
    out[paid_no_payment] = faturas.set_index("fatura_id").loc[paid_no_payment, "total_centavos"]
    return out.fillna(0)


def mrr(tl: pd.DataFrame, faturas: pd.DataFrame, pagamentos: pd.DataFrame, excluded: set[int],
        pagantes: list[str]) -> pd.DataFrame:
    """MRR no fim do mês: soma, para cada assinatura pagante (ativo ou cancelamento agendado) no
    último segundo do mês, do valor recebido da fatura que cobre aquele dia, normalizado ao mês
    (anual / 12). Assinatura inadimplente não entra (vira "MRR em risco")."""
    cash = invoice_cash(faturas, pagamentos)
    f = faturas.assign(caixa=faturas["fatura_id"].map(cash))
    f["meses"] = np.where(f["periodo_fim"] - f["periodo_inicio"] > pd.Timedelta(days=40), 12, 1)
    rows = []
    for p in MONTHS:
        t = eom(p)
        st = at_instant(tl, t)
        st = st[~st["conta_id"].isin(excluded)]
        day = t.normalize()
        cov = f[(f["periodo_inicio"] <= day) & (f["periodo_fim"] >= day)]
        cov = cov.groupby("assinatura_id").agg(caixa=("caixa", "sum"), meses=("meses", "max"))
        st = st.join(cov, on="assinatura_id")
        st["mrr"] = (st["caixa"] / st["meses"]).fillna(0)
        paying = st[st["estado"].isin(pagantes)]
        row = {"mes": str(p), "mrr_centavos": int(round(paying["mrr"].sum())),
               "mrr_em_risco_centavos": int(round(st.loc[st["estado"] == "inadimplente", "mrr"].sum())),
               "assinaturas_pagantes": int(len(paying))}
        for pid, name in PLAN_NAMES.items():
            row[f"mrr_{name}_centavos"] = int(round(paying.loc[paying["plano_id"] == pid, "mrr"].sum()))
            row[f"assinantes_{name}"] = int(paying.loc[paying["plano_id"] == pid, "conta_id"].nunique())
        rows.append(row)
    return pd.DataFrame(rows)


def subscribers_and_churn(spans: pd.DataFrame, excluded: set[int]) -> pd.DataFrame:
    """Assinantes ativos (contas vigentes no fim do mês) e churn mensal = contas cujo período
    vigente terminou no mês / contas vigentes no início do mês."""
    sp = spans[~spans["conta_id"].isin(excluded)]
    rows = []
    for p in MONTHS:
        b, e = p.to_timestamp(how="start"), eom(p)
        active_b = sp[(sp["inicio"] <= b) & (sp["fim"] > b)]["conta_id"].nunique()
        active_e = sp[(sp["inicio"] <= e) & (sp["fim"] > e)]["conta_id"].nunique()
        ended = sp[sp["churn"] & (sp["fim"] >= b) & (sp["fim"] <= e)]
        started = sp[(sp["inicio"] >= b) & (sp["inicio"] <= e)]
        first = sp.groupby("conta_id")["inicio"].transform("min")
        reat = started[started["inicio"] > first.loc[started.index]]
        rows.append({"mes": str(p), "ativos_inicio": active_b, "ativos_fim": active_e,
                     "novos": int((started["inicio"] == first.loc[started.index]).sum()), "reativacoes": len(reat),
                     "churn": len(ended), "churn_voluntario": int((ended["tipo_churn"] == "voluntario").sum()),
                     "churn_involuntario": int((ended["tipo_churn"] == "involuntario").sum()),
                     "taxa_churn": len(ended[ended["inicio"] < b]) / active_b if active_b else np.nan})
    return pd.DataFrame(rows)


def cohorts(spans: pd.DataFrame, excluded: set[int], horizon: int = 12) -> pd.DataFrame:
    """Retenção por coorte do primeiro mês de assinatura: % da coorte vigente no fim do mês k."""
    sp = spans[~spans["conta_id"].isin(excluded)]
    first = sp.groupby("conta_id")["inicio"].min().dt.to_period("M")
    rows = []
    for coh, contas in first.groupby(first):
        ids = set(contas.index)
        g = sp[sp["conta_id"].isin(ids)]
        for k in range(horizon + 1):
            p = coh + k
            if p > MONTHS[-1]:
                break
            e = eom(p)
            alive = g[(g["inicio"] <= e) & (g["fim"] > e)]["conta_id"].nunique()
            rows.append({"coorte": str(coh), "k": k, "base": len(ids), "retidos": alive, "retencao": alive / len(ids)})
    return pd.DataFrame(rows)


def engagement_month(plays: pd.DataFrame, spans: pd.DataFrame, excluded: set[int], mes: str,
                     drop_perfil_days: pd.DataFrame | None = None) -> dict:
    """Horas assistidas no mês por assinante ativo no fim do mês (pessoas reais apenas)."""
    p = pd.Period(mes, "M")
    e = eom(p)
    act = set(spans[(spans["inicio"] <= e) & (spans["fim"] > e)]["conta_id"]) - excluded
    r = plays[plays["conta_id"].isin(act)] if len(plays) else plays
    if drop_perfil_days is not None and len(drop_perfil_days) and len(r):
        key = r["perfil_id"].astype(str) + "|" + r["dia_local"].astype(str)
        dk = drop_perfil_days["perfil_id"].astype(str) + "|" + drop_perfil_days["dia_local"].astype(str)
        r = r[~key.isin(set(dk))]
    horas = float(r["segundos_assistidos"].clip(lower=0).sum() / 3600) if len(r) else 0.0
    pdays = r.groupby([r["perfil_id"], r["dia_local"]])["segundos_assistidos"].sum() / 3600 if len(r) else pd.Series(dtype=float)
    return {"mes": mes, "horas_assistidas": horas, "assinantes_ativos": len(act),
            "horas_por_assinante": horas / len(act) if act else np.nan,
            "contas_com_uso": int(r["conta_id"].nunique()) if len(r) else 0,
            "mediana_horas_perfil_dia": float(pdays.median()) if len(pdays) else np.nan,
            "reproducoes": len(r)}

