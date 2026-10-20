"""Formato único das marcações produzidas pelas regras de limpeza.

Papel: cada regra devolve o que tocou como linhas (regra, técnica, tabela, chave, ação, detalhe),
       para que o relatório de qualidade e a avaliação contem tudo do mesmo jeito.
Entrada: chaves afetadas por uma regra.
Saída: DataFrame de flags.
Dependências: pandas.

Ações possíveis: remover, corrigir, limitar, imputar, sinalizar, quarentena, excluir_das_metricas.
"""

from __future__ import annotations

import pandas as pd

COLUMNS = ["regra", "tecnica", "tabela", "chave", "acao", "detalhe"]
ACTIONS = {"remover", "corrigir", "limitar", "imputar", "sinalizar", "quarentena", "excluir_das_metricas"}


def make(regra: str, tecnica: str, tabela: str, chave, acao: str, detalhe=None) -> pd.DataFrame:
    assert acao in ACTIONS, acao
    chave = pd.Series(chave).astype("int64").to_numpy() if len(chave) else []
    df = pd.DataFrame({"chave": chave})
    df["regra"], df["tecnica"], df["tabela"], df["acao"] = regra, tecnica, tabela, acao
    df["detalhe"] = None if detalhe is None else (list(map(str, detalhe)) if not isinstance(detalhe, str) else detalhe)
    return df[COLUMNS]


def concat(parts: list[pd.DataFrame]) -> pd.DataFrame:
    parts = [p for p in parts if p is not None and len(p)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLUMNS)
