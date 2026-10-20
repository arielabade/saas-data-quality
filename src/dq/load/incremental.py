"""Carga incremental idempotente do uso, com reprocessamento de eventos atrasados.

Papel: simular a chegada do uso em lotes (por `recebido_em`) e manter um armazém particionado
       por mês do evento, regravando só o que mudou.
Entrada: sessões e reproduções já limpas (com `recebido_em`), parâmetros de carga, data de corte.
Saída: run_dir/warehouse/<tabela>/mes=AAAA-MM.parquet, _estado.json e a lista de meses alterados.
Dependências: pandas.

Como funciona:
1. Cada linha pertence ao lote do seu `recebido_em` (lotes de N dias).
2. Atraso: se o evento aconteceu antes de (início do lote - janela), ele chegou tarde demais para
   recalcular o passado sem reabrir um mês fechado: vai para a quarentena `atrasado_fora_da_janela`.
   Dentro da janela, entra no mês do EVENTO e esse mês é recalculado.
3. Idempotência: cada partição tem um hash do conteúdo. Rodar de novo com a mesma entrada não
   regrava nada; um atrasado que chega só muda o hash do mês dele.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ORIGIN = pd.Timestamp("2023-10-01")


def content_hash(df: pd.DataFrame) -> str:
    if df.empty:
        return "vazio"
    h = pd.util.hash_pandas_object(df.reset_index(drop=True), index=False)
    return f"{len(df)}-{int(h.sum()) & 0xFFFFFFFFFFFF:x}"


def assign_batches(df: pd.DataFrame, batch_days: int, window_days: int) -> pd.DataFrame:
    df = df.copy()
    n = ((df["recebido_em"] - ORIGIN).dt.days // batch_days).clip(lower=0)
    df["lote_inicio"] = ORIGIN + pd.to_timedelta(n * batch_days, unit="D")
    df["fora_da_janela"] = df["inicio_em"] < df["lote_inicio"] - pd.Timedelta(days=window_days)
    return df


class Warehouse:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.state_path = folder / "_estado.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {"particoes": {}, "marts": {}}

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=1, sort_keys=True))

    def load(self, table: str, df: pd.DataFrame, key: str) -> tuple[set[str], pd.DataFrame]:
        """Grava as partições cujo conteúdo mudou. Retorna (meses alterados, linhas em quarentena)."""
        late = df[df["fora_da_janela"]]
        ok = df[~df["fora_da_janela"]].drop(columns=["lote_inicio", "fora_da_janela"])
        ok = ok.assign(mes=ok["inicio_em"].dt.to_period("M").astype(str)).sort_values(key)
        changed: set[str] = set()
        seen = set()
        tdir = self.folder / table
        for mes, part in ok.groupby("mes", sort=True):
            seen.add(mes)
            part = part.drop(columns="mes").reset_index(drop=True)
            h = content_hash(part)
            sk = f"{table}/{mes}"
            if self.state["particoes"].get(sk) != h:
                tdir.mkdir(parents=True, exist_ok=True)
                part.to_parquet(tdir / f"mes={mes}.parquet", index=False)
                self.state["particoes"][sk] = h
                changed.add(mes)
        for sk in [k for k in self.state["particoes"] if k.startswith(f"{table}/") and k.split("/")[1] not in seen]:
            (tdir / f"mes={sk.split('/')[1]}.parquet").unlink(missing_ok=True)
            del self.state["particoes"][sk]
            changed.add(sk.split("/")[1])
        return changed, late

    def read(self, table: str, months: set[str] | None = None) -> pd.DataFrame:
        tdir = self.folder / table
        files = sorted(tdir.glob("mes=*.parquet")) if tdir.exists() else []
        if months is not None:
            files = [f for f in files if f.stem.split("=")[1] in months]
        return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files else pd.DataFrame()

    def months(self, table: str) -> list[str]:
        return sorted(k.split("/")[1] for k in self.state["particoes"] if k.startswith(f"{table}/"))
