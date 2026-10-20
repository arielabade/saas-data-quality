"""Limites físicos do uso: tempo negativo, maior que o conteúdo, mais de 24 h por aparelho no dia
e sessões abertas a noite toda.

Papel: tornar o tempo assistido fisicamente possível antes de qualquer média ou soma.
Entrada: reproducoes e sessoes_app (staging, horários já em UTC real).
Saída: tabelas corrigidas + flags.
Dependências: pandas, numpy.

Decisões por caso:
- negativo: CORRIGIR com fim - início (limitado à duração) quando os horários são válidos; se não,
  zera e sinaliza. Remover a linha perderia a informação de que houve uma reprodução.
- maior que a duração (x1,05): LIMITAR à duração. Quem deixou o player aberto assistiu no
  máximo o conteúdo inteiro; o excedente é tempo de tela, não de conteúdo.
- soma por aparelho no dia > 24 h: LIMITAR proporcionalmente (só acontece com sobreposição
  impossível no mesmo aparelho).
- sessão: termina no máximo 10 min depois da última reprodução (CORRIGIR o fim).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dq.clean import flags


def apply_limits(r: pd.DataFrame, s: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    out = []
    dur = r["duracao_conteudo_seg"]
    sec = r["segundos_assistidos"].astype(float)

    neg = sec < 0
    span = (r["fim_em"] - r["inicio_em"]).dt.total_seconds()
    fixable = neg & (span > 0)
    sec = sec.where(~fixable, np.minimum(span, dur.fillna(span)))
    sec = sec.where(~(neg & ~fixable), 0)
    out.append(flags.make("tempo_negativo", "regra_fisica", "reproducoes", r.loc[fixable, "reproducao_id"], "corrigir"))
    out.append(flags.make("tempo_negativo_sem_horario", "regra_fisica", "reproducoes", r.loc[neg & ~fixable, "reproducao_id"], "sinalizar"))

    over = dur.notna() & (sec > dur * cfg["fator_duracao"])
    sec = sec.where(~over, dur)
    out.append(flags.make("tempo_maior_que_conteudo", "regra_fisica", "reproducoes", r.loc[over, "reproducao_id"], "limitar"))
    r = r.copy()
    r["segundos_assistidos"] = sec.round().astype("int64")
    r.loc[over, "percentual_concluido"] = r.loc[over, "percentual_concluido"].clip(upper=100)
    end_cap = r["inicio_em"] + pd.to_timedelta(r["segundos_assistidos"] + 600, unit="s")
    long_end = over & (r["fim_em"] > end_cap)
    r.loc[long_end, "fim_em"] = end_cap[long_end]

    day = r["inicio_em"].dt.floor("D")
    tot = r.groupby([r["dispositivo_id"], day])["segundos_assistidos"].transform("sum")
    cap = cfg["horas_dia_dispositivo"] * 3600
    big = tot > cap
    r.loc[big, "segundos_assistidos"] = (r.loc[big, "segundos_assistidos"] * cap / tot[big]).round().astype("int64")
    out.append(flags.make("mais_de_24h_por_aparelho", "regra_fisica", "reproducoes", r.loc[big, "reproducao_id"], "limitar"))

    last = r.groupby("sessao_id")["fim_em"].max()
    s = s.copy()
    lim = s["sessao_id"].map(last) + pd.Timedelta(minutes=cfg["sessao_folga_min"])
    cut = lim.notna() & (s["fim_em"] > lim + pd.Timedelta(hours=2))
    s.loc[cut, "fim_em"] = lim[cut]
    out.append(flags.make("sessao_aberta_demais", "regra_fisica", "sessoes_app", s.loc[cut, "sessao_id"], "corrigir"))
    return r, s, flags.concat(out)


def physical_violations(r: pd.DataFrame, cfg: dict) -> pd.Series:
    """Detector (sem tratar): reprodução impossível. Usado na comparação de técnicas."""
    dur = r["duracao_conteudo_seg"]
    sec = r["segundos_assistidos"]
    day = r["inicio_em"].dt.floor("D")
    tot = sec.clip(lower=0).groupby([r["dispositivo_id"], day]).transform("sum")
    return (sec < 0) | (dur.notna() & (sec > dur * cfg["fator_duracao"])) | (tot > cfg["horas_dia_dispositivo"] * 3600)
