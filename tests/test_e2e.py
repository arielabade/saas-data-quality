"""Ponta a ponta no perfil pequeno: raw -> marts, idempotência e reprocessamento de atrasados."""

from __future__ import annotations

import hashlib

import pandas as pd
import pytest

pytestmark = pytest.mark.e2e


def _digest(folder):
    h = hashlib.sha1()
    for p in sorted(folder.rglob("*.parquet")):
        if "staging" in p.parts:
            continue
        h.update(p.relative_to(folder).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def test_etl_ponta_a_ponta_idempotente(e2e_data):
    from dq.pipeline import run_etl

    run = e2e_data["runs"] / "e2e"
    rep1 = run_etl(e2e_data["raw"], run, verbose=False)
    d1 = _digest(run)
    rep2 = run_etl(e2e_data["raw"], run, verbose=False)
    assert _digest(run) == d1, "rodar o ETL duas vezes mudou a saída"
    assert rep2["meses_engajamento_recalculados"] == [] and rep2["meses_particoes_alteradas"] == []
    assert all(c["falhas"] == 0 for c in rep1["contratos"] if c["camada"] in ("clean", "marts"))
    mrr = pd.read_parquet(run / "marts" / "mrr.parquet")
    assert len(mrr) == 37 and (mrr["mrr_centavos"] >= 0).all() and mrr["mrr_centavos"].iloc[-1] > 0


def test_reprocessar_atrasados_recalcula_so_o_necessario(e2e_data):
    from dq.pipeline import run_etl

    run = e2e_data["runs"] / "e2e_incremental"
    run_etl(e2e_data["raw"], run, cutoff="2026-06-30 23:59:59", verbose=False)
    rep = run_etl(e2e_data["raw"], run, cutoff="2026-07-07 23:59:59", verbose=False)
    changed = set(rep["meses_engajamento_recalculados"])
    assert "2026-07" in changed or "2026-06" in changed
    assert len(changed) < 10, f"uma semana de lotes recalculou meses demais: {sorted(changed)}"


def test_limpeza_aproxima_da_verdade(e2e_data):
    from dq.pipeline import ALL_RULES_OFF, run_etl

    runs = e2e_data["runs"]
    run_etl(e2e_data["raw_reference"], runs / "e2e_verdade", verbose=False)
    run_etl(e2e_data["raw"], runs / "e2e_ingenua", rules=ALL_RULES_OFF, verbose=False)
    run_etl(e2e_data["raw"], runs / "e2e_limpa", verbose=False)
    m = {v: pd.read_parquet(runs / f"e2e_{v}" / "marts" / "mrr.parquet").set_index("mes")["mrr_centavos"]
         for v in ("verdade", "ingenua", "limpa")}
    since = m["verdade"].index >= "2024-06"
    err = {v: (m[v][since] - m["verdade"][since]).abs().sum() for v in ("ingenua", "limpa")}
    assert err["limpa"] < err["ingenua"]
