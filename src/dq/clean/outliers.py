"""Detecção de outliers no uso: IQR, z-score robusto, regra física, sazonal e Isolation Forest.

Papel: comparar técnicas que respondem perguntas diferentes:
       - IQR e z robusto (mediana/MAD): "este perfil-dia é estatisticamente raro?";
       - regra física: "isto é possível?";
       - sazonal: "este DIA da plataforma foge do esperado para a época, e há explicação?";
       - Isolation Forest: "o PADRÃO desta conta (horários, telas, regiões) é anômalo?".
Entrada: reproducoes/sessoes (staging ou clean), contas, planos, episódios, calendário.
Saída: marcações por unidade (perfil-dia, dia ou conta-mês). Tratamento padrão: SINALIZAR.
Dependências: pandas, numpy, scikit-learn.

Decisão de negócio: outlier estatístico não é erro. Uma maratona de estreia é exatamente o
que o negócio quer; tirá-la derruba o engajamento do mês. Só a regra física remove/limita;
o Isolation Forest só exclui quando o padrão explicado é de robô.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

from dq.domain import HOLIDAYS, TZ_OFFSET_H


def local_time(ts: pd.Series, conta: pd.Series, tz: pd.Series) -> pd.Series:
    """UTC -> hora local da conta (fusos fixos; o Brasil não tem horário de verão desde 2019)."""
    off = conta.map(tz).fillna("America/Sao_Paulo").map(TZ_OFFSET_H).astype(int)
    return ts + pd.to_timedelta(off, unit="h")


def perfil_day(r: pd.DataFrame, tz: pd.Series) -> pd.DataFrame:
    """Unidade de análise de comportamento: horas assistidas por perfil no dia LOCAL."""
    loc = local_time(r["inicio_em"], r["conta_id"], tz)
    g = r.assign(dia=loc.dt.floor("D"), h=r["segundos_assistidos"].clip(lower=0) / 3600).groupby(["perfil_id", "dia"])
    out = g.agg(conta_id=("conta_id", "first"), horas=("h", "sum"), reproducoes=("reproducao_id", "size")).reset_index()
    out["mes"] = out["dia"].dt.to_period("M").astype(str)
    return out


def iqr_flags(pdays: pd.DataFrame, k: float, col: str = "horas") -> pd.Series:
    """Acima de Q3 + k·IQR dentro do mês (o uso cresce ao longo do tempo; o mês é a referência)."""
    q = pdays.groupby("mes")[col].quantile([.25, .75]).unstack()
    lim = pdays["mes"].map(q[.75] + k * (q[.75] - q[.25]))
    return pdays[col] > lim


def robust_z(x: pd.Series) -> pd.Series:
    med = x.median()
    mad = (x - med).abs().median()
    return 0.6745 * (x - med) / (mad if mad > 0 else 1e-9)


def mad_flags(pdays: pd.DataFrame, z: float, col: str = "horas") -> pd.Series:
    return pdays.groupby("mes")[col].transform(robust_z) > z


def physical_flags(r: pd.DataFrame, violations: pd.Series, tz: pd.Series) -> pd.DataFrame:
    """Perfil-dias com pelo menos uma reprodução fisicamente impossível."""
    loc = local_time(r["inicio_em"], r["conta_id"], tz)
    v = r.loc[violations, ["perfil_id"]].assign(dia=loc[violations].dt.floor("D"))
    return v.drop_duplicates()


# ------------------------------------------------------------------------------------- sazonal
def daily_series(pdays: pd.DataFrame) -> pd.Series:
    return pdays.groupby("dia")["horas"].sum().asfreq("D", fill_value=0.0)


def seasonal_flags(daily: pd.Series, window: int, z: float) -> pd.DataFrame:
    """Tendência (mediana móvel) + efeito do dia da semana + resíduo em z robusto, em log."""
    y = np.log1p(daily)
    trend = y.rolling(window, center=True, min_periods=window // 2).median()
    r0 = y - trend
    dow = r0.groupby(r0.index.dayofweek).transform("median")
    resid = r0 - dow
    zz = robust_z(resid.dropna()).reindex(resid.index)
    return pd.DataFrame({"horas": daily, "esperado": np.expm1(trend + dow), "z": zz, "anomalo": zz.abs() > z})


def naive_daily_flags(daily: pd.Series, z: float) -> pd.Series:
    """Linha de base: z robusto no total diário, sem tendência nem sazonalidade."""
    return robust_z(daily) > z


def explain_days(days: pd.DataFrame, r: pd.DataFrame, episodios: pd.DataFrame, share_min: float = 0.05) -> pd.DataFrame:
    """Para cada dia anômalo: feriado? estreia (temporada lançada até 3 dias antes com fatia
    relevante do dia)? Se nada explica, é erro provável."""
    out = days[days["anomalo"]].copy()
    if out.empty:
        out["explicacao"] = []
        return out
    rel = episodios.groupby(["titulo_id", "temporada"])["disponivel_desde"].min().dt.floor("D").reset_index()
    day = r["inicio_em"].dt.floor("D")
    expl = []
    for d, row in out.iterrows():
        if d.strftime("%m-%d") in HOLIDAYS:
            expl.append("feriado")
            continue
        if row["z"] < 0:
            expl.append("queda: perda de dados provável")
            continue
        recent = rel[(rel["disponivel_desde"] <= d) & (rel["disponivel_desde"] >= d - pd.Timedelta(days=3))]["titulo_id"]
        today = r[day == d]
        share = today["titulo_id"].isin(recent).mean() if len(today) else 0
        expl.append("estreia" if share >= share_min else "erro provável")
    out["explicacao"] = expl
    return out


# --------------------------------------------------------------------------- Isolation Forest
def max_concurrency(r: pd.DataFrame) -> pd.Series:
    """Maior número de reproduções simultâneas por conta-mês (varredura de eventos +1/-1)."""
    end = r["fim_em"].where(r["fim_em"] > r["inicio_em"], r["inicio_em"] + pd.Timedelta(seconds=1))
    ev = pd.concat([
        pd.DataFrame({"conta_id": r["conta_id"].to_numpy(), "t": r["inicio_em"].to_numpy(), "d": 1}),
        pd.DataFrame({"conta_id": r["conta_id"].to_numpy(), "t": end.to_numpy(), "d": -1}),
    ]).sort_values(["conta_id", "t", "d"])
    ev["c"] = ev.groupby("conta_id")["d"].cumsum()
    ev["mes"] = pd.to_datetime(ev["t"]).dt.to_period("M").astype(str)
    return ev[ev["d"] == 1].groupby(["conta_id", "mes"])["c"].max()


def account_features(r: pd.DataFrame, s: pd.DataFrame, tz: pd.Series, screens: pd.Series) -> pd.DataFrame:
    r = r.dropna(subset=["conta_id"]).copy()
    r["conta_id"] = r["conta_id"].astype("int64")
    loc = local_time(r["inicio_em"], r["conta_id"], tz)
    r["mes"] = loc.dt.to_period("M").astype(str)
    r["hora"] = loc.dt.hour
    r["dia"] = loc.dt.floor("D")
    r["curta"] = r["segundos_assistidos"].between(0, 180)
    r["madrugada"] = r["hora"].between(1, 5)
    g = r.groupby(["conta_id", "mes"])
    cnt = r.groupby(["conta_id", "mes", "hora"]).size()
    pr = cnt / cnt.groupby(level=[0, 1]).transform("sum")
    entropy = (-(pr * np.log(pr))).groupby(level=[0, 1]).sum()
    f = pd.DataFrame({
        "reproducoes": g.size(),
        "dias_ativos": g["dia"].nunique(),
        "horas": g["segundos_assistidos"].sum().clip(lower=0) / 3600,
        "frac_curtas": g["curta"].mean(),
        "frac_madrugada": g["madrugada"].mean(),
        "entropia_hora": entropy,
        "dispositivos": g["dispositivo_id"].nunique(),
    })
    f["reproducoes_por_dia"] = f["reproducoes"] / f["dias_ativos"]
    f["horas_por_dia"] = f["horas"] / f["dias_ativos"]
    ss = s.dropna(subset=["conta_id"]).assign(mes=lambda x: local_time(x["inicio_em"], x["conta_id"], tz).dt.to_period("M").astype(str))
    f["regioes"] = ss.groupby(["conta_id", "mes"])["regiao"].nunique().reindex(f.index).fillna(0)
    f["telas_simultaneas"] = max_concurrency(r).reindex(f.index).fillna(1)
    lim = pd.Series(f.index.get_level_values(0), index=f.index).map(screens).fillna(2)
    f["telas_acima_do_limite"] = (f["telas_simultaneas"] - lim).clip(lower=0)
    return f.drop(columns=["dias_ativos"])


FEATURES = ["reproducoes_por_dia", "horas_por_dia", "frac_curtas", "frac_madrugada", "entropia_hora",
            "dispositivos", "regioes", "telas_simultaneas", "telas_acima_do_limite"]


def isolation_forest(feat: pd.DataFrame, contamination: float, seed: int) -> pd.DataFrame:
    X = RobustScaler().fit_transform(np.log1p(feat[FEATURES].clip(lower=0)))
    model = IsolationForest(n_estimators=300, contamination=contamination, random_state=seed)
    out = feat.copy()
    out["score"] = -model.fit(X).score_samples(X)
    out["anomalo"] = model.predict(X) == -1
    out["explicacao"] = np.select(
        [out["anomalo"] & (out["frac_curtas"] > 0.6) & (out["reproducoes_por_dia"] > 15),
         out["anomalo"] & (out["telas_acima_do_limite"] > 0) & (out["regioes"] >= 2),
         out["anomalo"]],
        ["robô", "compartilhamento acima do limite", "atípico"], "")
    return out
