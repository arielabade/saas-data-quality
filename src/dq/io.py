"""Leitura e escrita de tabelas em Parquet por camada.

Papel: padronizar como cada camada (source, raw, staging, clean, marts) é gravada e lida.
Entrada/saída: DataFrames pandas <-> pastas com um Parquet por tabela.
Dependências: pandas, pyarrow.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd


def write_table(df: pd.DataFrame, folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.parquet"
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)  # escrita atômica: um leitor nunca vê arquivo pela metade
    return path


def read_table(folder: Path, name: str, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(folder / f"{name}.parquet", columns=columns)


def read_layer(folder: Path, names: list[str]) -> dict[str, pd.DataFrame]:
    return {n: read_table(folder, n) for n in names}


def write_layer(tables: dict[str, pd.DataFrame], folder: Path, clean: bool = True) -> None:
    if clean and folder.exists():
        shutil.rmtree(folder)
    for n, df in tables.items():
        write_table(df, folder, n)
