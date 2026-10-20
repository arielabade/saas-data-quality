"""IDs de dispositivo trocando para o mesmo aparelho (reinstalação do app).

Papel: unificar dispositivo_id que representam o mesmo aparelho físico, para que contagem de
       telas, limite de 24 h por aparelho e detecção de compartilhamento não sejam inflados.
Entrada: dispositivos (staging) e sessoes_app (com horários já corrigidos).
Saída: mapa dispositivo_id -> dispositivo canônico + flags (ação `corrigir`).
Dependências: pandas.

Regra: na mesma conta, mesmo tipo e plataforma, um id novo cujo primeiro uso começa depois do
último uso do anterior (com no máximo 14 dias de intervalo) e sem nenhum uso simultâneo é o mesmo
aparelho. Dois celulares usados em paralelo nunca são unidos: isso seria apagar um membro da casa.
"""

from __future__ import annotations

import pandas as pd

from dq.clean import flags


def unify(dispositivos: pd.DataFrame, sessoes: pd.DataFrame, slack_days: int) -> tuple[pd.Series, pd.DataFrame]:
    use = sessoes.groupby("dispositivo_id")["inicio_em"].agg(primeiro="min", ultimo="max")
    d = dispositivos[["dispositivo_id", "conta_id", "tipo", "plataforma"]].merge(use, left_on="dispositivo_id", right_index=True)
    d = d.sort_values(["conta_id", "tipo", "plataforma", "primeiro"])
    mapping: dict[int, int] = {}
    slack = pd.Timedelta(days=slack_days)
    for _, g in d.groupby(["conta_id", "tipo", "plataforma"], sort=False):
        if len(g) < 2:
            continue
        canon, last = None, None
        for row in g.itertuples():
            if canon is not None and last - pd.Timedelta(hours=1) <= row.primeiro <= last + slack:
                mapping[row.dispositivo_id] = canon
                last = max(last, row.ultimo)
            else:
                canon, last = row.dispositivo_id, row.ultimo
    m = pd.Series(mapping, dtype="int64")
    return m, flags.make("dispositivo_unificado", "sequencia_sem_sobreposicao", "dispositivos", m.index, "corrigir", m.to_numpy())


def apply(df: pd.DataFrame, mapping: pd.Series) -> pd.DataFrame:
    if len(mapping):
        df["dispositivo_id"] = df["dispositivo_id"].map(mapping).fillna(df["dispositivo_id"]).astype("int64")
    return df
