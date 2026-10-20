"""Registro de defeitos (o "gabarito" deste projeto, gerado pelo próprio injetor).

Papel: acumular cada alteração feita pelo injetor numa tabela auditável.
Entrada: chamadas `add(...)` do injetor.
Saída: data/defect_log/defect_log.parquet com uma linha por (tabela, chave, coluna, tipo).
Dependências: pandas.

Categorias:
- defeito: erro de dados; não existe na verdade de referência.
- anomalia: comportamento real que pede ação (ex.: compartilhamento acima do limite); está na referência.
- legitimo: outlier verdadeiro que a limpeza NÃO pode derrubar; está na referência.

Só src/dq/corrupt e src/dq/evaluate podem ler este registro (tests/test_defect_log_guard.py).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["categoria", "tipo", "tabela", "chave", "coluna", "valor_original", "valor_sujo",
           "conta_id", "perfil_id", "dispositivo_id", "data"]


class DefectLog:
    def __init__(self) -> None:
        self._parts: list[pd.DataFrame] = []

    def add(self, categoria: str, tipo: str, tabela: str, chave, coluna: str | None = None,
            original=None, sujo=None, conta_id=None, perfil_id=None, dispositivo_id=None, data=None) -> None:
        chave = np.atleast_1d(np.asarray(chave))
        n = len(chave)
        if n == 0:
            return

        def col(v, as_str=False):
            if v is None:
                return [None] * n
            arr = pd.Series(np.broadcast_to(np.asarray(v, dtype=object), (n,)) if np.ndim(v) == 0 else list(v))
            return arr.map(lambda x: None if x is None or (isinstance(x, float) and np.isnan(x)) else str(x)) if as_str else arr

        df = pd.DataFrame({
            "categoria": categoria, "tipo": tipo, "tabela": tabela, "chave": chave.astype("int64"),
            "coluna": coluna, "valor_original": col(original, True), "valor_sujo": col(sujo, True),
            "conta_id": pd.array(col(conta_id), dtype="Int64"), "perfil_id": pd.array(col(perfil_id), dtype="Int64"),
            "dispositivo_id": pd.array(col(dispositivo_id), dtype="Int64"),
            "data": pd.to_datetime(pd.Series(col(data))).dt.normalize(),
        })
        self._parts.append(df[COLUMNS])

    def frame(self) -> pd.DataFrame:
        if not self._parts:
            return pd.DataFrame(columns=COLUMNS)
        df = pd.concat(self._parts, ignore_index=True)
        df.insert(0, "defeito_id", np.arange(1, len(df) + 1))
        return df

    def write(self, folder: Path) -> pd.DataFrame:
        df = self.frame()
        folder.mkdir(parents=True, exist_ok=True)
        df.to_parquet(folder / "defect_log.parquet", index=False)
        resumo = df.groupby(["categoria", "tipo", "tabela"]).size().rename("linhas").reset_index()
        resumo.to_csv(folder / "resumo.csv", index=False)
        return df
