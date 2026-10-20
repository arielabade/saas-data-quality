"""Injetor de sujeira com registro de defeitos.

Papel: copiar a base de referência e produzir duas camadas raw:
       - data/raw_reference: a base + outliers legítimos e anomalias reais, sem defeitos
         (é a "verdade" contra a qual o ETL é medido);
       - data/raw: a mesma base com defeitos realistas injetados.
       Cada alteração vai para data/defect_log/.
Entrada: data/source (snapshot do MySQL) e config/corruption.yaml (semente e taxas).
Saída: data/raw_reference/*.parquet, data/raw/*.parquet, data/defect_log/defect_log.parquet.
Dependências: dq.corrupt.{base,legit,defects,log}.

O ETL nunca lê data/defect_log (garantido por tests/test_defect_log_guard.py).
"""

from __future__ import annotations

import time

from dq.config import load_yaml, settings
from dq.corrupt.base import Ctx, add_received_at, to_raw
from dq.corrupt.defects import apply_defects
from dq.corrupt.legit import apply_legit
from dq.corrupt.log import DefectLog
from dq.io import read_layer, write_layer


def run() -> None:
    t0 = time.time()
    cfg = settings()
    ccfg = load_yaml("corruption")
    tables = read_layer(cfg["paths"]["source"], cfg["extract"]["tables"])
    ctx = Ctx(tables, ccfg["seed"])
    add_received_at(ctx.t, ctx.rng)
    log = DefectLog()

    apply_legit(ctx, log, ccfg)
    print(f"[corrupt] outliers legítimos e anomalias reais: {len(log.frame()):,d} registros ({time.time() - t0:.0f}s)")
    write_layer(to_raw(ctx), cfg["paths"]["raw_reference"])

    apply_defects(ctx, log, ccfg)
    write_layer(to_raw(ctx), cfg["paths"]["raw"])
    df = log.write(cfg["paths"]["defect_log"])
    print(f"[corrupt] {len(df):,d} entradas no registro ({time.time() - t0:.0f}s)")
    print(df.groupby(["categoria", "tipo"]).size().to_string())


if __name__ == "__main__":
    run()
