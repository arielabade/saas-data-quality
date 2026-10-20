"""Deduplicação por chave idempotente e janela de tempo.

Papel: remover entregas repetidas do mesmo fato:
       - pagamentos: webhook do gateway entregue 2+ vezes e retentativa registrada de novo como
         pagamento separado (mesma fatura, tipo, nº da tentativa, status e valor em até 1 h);
       - uso: reprocessamento de lote que reinsere sessões e reproduções com ids novos
         (mesmo perfil, aparelho, conteúdo e instante de início).
Entrada: pagamentos / sessoes_app / reproducoes em staging.
Saída: tabela sem duplicatas + flags (ação `remover`).
Dependências: pandas.

Decisão: fica a PRIMEIRA entrega (menor horário de processamento/recebimento): é a que o sistema
de origem gerou; as outras são reentregas. Uma tentativa nova de cobrança tem número de
tentativa diferente e dias de distância, então não colide com a chave.
"""

from __future__ import annotations

import pandas as pd

from dq.clean import flags


def dedup_payments(pg: pd.DataFrame, key: list[str], window_s: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = pg.sort_values(key + ["processado_em", "pagamento_id"]).copy()
    k = d[key].astype("string").fillna("<nulo>").agg("|".join, axis=1)
    gap = d["processado_em"].diff().dt.total_seconds()
    same_key = k.eq(k.shift())
    dup = same_key & (gap <= window_s)
    removed = d.loc[dup, "pagamento_id"]
    f = flags.make("pagamento_duplicado", "chave_idempotente+janela", "pagamentos", removed, "remover")
    return pg[~pg["pagamento_id"].isin(removed)].copy(), f


def dedup_usage(df: pd.DataFrame, key: list[str], id_col: str, table: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = df.sort_values(["recebido_em", id_col])
    dup = d.duplicated(key, keep="first")
    removed = d.loc[dup, id_col]
    f = flags.make("uso_duplicado", "chave_natural", table, removed, "remover")
    return df[~df[id_col].isin(removed)].copy(), f
