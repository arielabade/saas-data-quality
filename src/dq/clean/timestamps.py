"""Fuso horário misturado, relógio errado do aparelho e eventos atrasados.

Papel: garantir que todo `*_em` de uso esteja em UTC real, e separar "chegou tarde" de "hora errada".
Entrada: sessoes_app e reproducoes em staging (com `recebido_em`, hora do servidor, confiável).
Saída: tabelas com horários corrigidos + flags; perfil de relógio por aparelho.
Dependências: pandas, numpy, dq.domain.

Três regras, nesta ordem:
1. Fuso: hora do web sem offset (`ts_sem_fuso`) é hora local da conta -> converte para UTC.
   Detecção por formato, não por estatística: o contrato do web é mandar offset.
2. Relógio: o desvio (recebido_em - fim) de um aparelho sadio é de segundos. Se a mediana do
   aparelho passa de 30 min e ao menos 60% das linhas estão perto dela, o relógio está deslocado:
   soma-se o desvio a todas as linhas do aparelho. Linhas antes de 2023 (relógio zerado) são
   reconstruídas a partir de recebido_em menos a duração.
3. Atraso: desvio grande numa linha isolada (aparelho com mediana normal) é sincronização offline.
   O horário está certo; só a chegada atrasou. Não se corrige nada: marca-se para a carga.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dq.clean import flags
from dq.domain import TZ_OFFSET_H, UF_TZ


def account_tz(contas: pd.DataFrame, default: str = "America/Sao_Paulo") -> pd.Series:
    """Fuso de cada conta: pela UF; sem UF, o padrão do país (ver nulls.py para a região imputada)."""
    return pd.Series(contas["uf"].map(UF_TZ).fillna(default).to_numpy(), index=contas["conta_id"])


def fix_timezone(df: pd.DataFrame, tz: pd.Series, table: str, key: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    m = df["ts_sem_fuso"].to_numpy()
    if not m.any():
        return df, flags.make("fuso_misturado", "contrato_de_formato", table, [], "corrigir")
    off = df.loc[m, "conta_id"].map(tz).fillna("America/Sao_Paulo").map(TZ_OFFSET_H)
    delta = pd.to_timedelta(-off.astype(int), unit="h")
    for c in ("inicio_em", "fim_em"):
        df.loc[m, c] = (df.loc[m, c] + delta).to_numpy()
    return df, flags.make("fuso_misturado", "contrato_de_formato", table, df.loc[m, key], "corrigir")


def skew_seconds(df: pd.DataFrame) -> pd.Series:
    end = df["fim_em"].fillna(df["inicio_em"])
    end = end.where(end >= df["inicio_em"], df["inicio_em"])
    return (df["recebido_em"] - end).dt.total_seconds()


def clock_profile(frames: list[pd.DataFrame], min_dev_min: float, consistency: float, min_year: int) -> pd.DataFrame:
    """Desvio típico de relógio por aparelho, a partir de todas as linhas recebidas até agora."""
    parts = []
    for df in frames:
        ok = df["inicio_em"].dt.year >= min_year
        parts.append(pd.DataFrame({"dispositivo_id": df.loc[ok, "dispositivo_id"], "skew": skew_seconds(df[ok])}))
    s = pd.concat(parts)
    g = s.groupby("dispositivo_id")["skew"]
    med = g.median()
    near = (s["skew"] - s["dispositivo_id"].map(med)).abs() <= 600
    prof = pd.DataFrame({"desvio_mediano_seg": med, "consistencia": near.groupby(s["dispositivo_id"]).mean(), "linhas": g.size()})
    prof["relogio_errado"] = (prof["desvio_mediano_seg"].abs() > min_dev_min * 60) & (prof["consistencia"] >= consistency)
    # correção arredondada ao minuto: o resto é latência normal de rede
    prof["correcao_seg"] = np.where(prof["relogio_errado"], (prof["desvio_mediano_seg"] / 60).round() * 60, 0)
    return prof


def fix_clock(df: pd.DataFrame, prof: pd.DataFrame, table: str, key: str, min_year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    corr = df["dispositivo_id"].map(prof["correcao_seg"]).fillna(0)
    m = (corr != 0).to_numpy()
    for c in ("inicio_em", "fim_em"):
        df.loc[m, c] = (df.loc[m, c] + pd.to_timedelta(corr[m], unit="s")).to_numpy()
    out = [flags.make("relogio_errado", "desvio_por_aparelho", table, df.loc[m, key], "corrigir")]
    # relógio zerado (ano 2000): reconstrói a partir da hora do servidor
    reset = (df["inicio_em"].dt.year < min_year).to_numpy()
    if reset.any():
        dur = (df.loc[reset, "fim_em"] - df.loc[reset, "inicio_em"]).fillna(pd.Timedelta(0)).clip(lower=pd.Timedelta(0))
        df.loc[reset, "fim_em"] = (df.loc[reset, "recebido_em"] - pd.Timedelta(seconds=5)).to_numpy()
        df.loc[reset, "inicio_em"] = (df.loc[reset, "fim_em"] - dur).to_numpy()
        out.append(flags.make("relogio_zerado", "hora_do_servidor", table, df.loc[reset, key], "corrigir"))
    return df, flags.concat(out)


def mark_late(df: pd.DataFrame, table: str, key: str, hours: float = 6) -> pd.DataFrame:
    """Linhas que chegaram muito depois de acontecer (só informativo; a carga decide o que fazer)."""
    late = skew_seconds(df) > hours * 3600
    return flags.make("chegada_atrasada", "recebido_menos_ocorrido", table, df.loc[late, key], "sinalizar")
