"""Carga incremental: idempotência, atrasado dentro e fora da janela, recálculo só do necessário."""

from __future__ import annotations

import pandas as pd

from dq.load.incremental import Warehouse, assign_batches

T = pd.Timestamp


def _plays(extra: list[tuple] | None = None) -> pd.DataFrame:
    rows = [(1, T("2024-01-10 20:00"), T("2024-01-10 21:00")), (2, T("2024-02-10 20:00"), T("2024-02-10 21:00")),
            (3, T("2024-03-10 20:00"), T("2024-03-10 21:00"))] + (extra or [])
    return pd.DataFrame(rows, columns=["reproducao_id", "inicio_em", "recebido_em"]).assign(segundos_assistidos=600)


def _load(wh: Warehouse, df: pd.DataFrame, window: int = 30):
    return wh.load("reproducoes", assign_batches(df, 7, window), "reproducao_id")


def test_mesma_entrada_duas_vezes_nao_regrava_nada(tmp_path):
    wh = Warehouse(tmp_path)
    ch1, _ = _load(wh, _plays())
    wh.save()
    files = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*.parquet")}
    ch2, _ = _load(Warehouse(tmp_path), _plays())
    assert ch1 == {"2024-01", "2024-02", "2024-03"} and ch2 == set()
    assert files == {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*.parquet")}


def test_atrasado_dentro_da_janela_recalcula_so_o_mes_do_evento(tmp_path):
    wh = Warehouse(tmp_path)
    _load(wh, _plays())
    late = (4, T("2024-02-20 20:00"), T("2024-03-05 08:00"))       # celular offline: chega 14 dias depois
    ch, q = _load(wh, _plays([late]))
    assert ch == {"2024-02"} and q.empty
    assert 4 in set(wh.read("reproducoes", {"2024-02"})["reproducao_id"])


def test_atrasado_fora_da_janela_vai_para_quarentena(tmp_path):
    wh = Warehouse(tmp_path)
    _load(wh, _plays(), window=3)
    late = (4, T("2024-02-20 20:00"), T("2024-03-05 08:00"))
    ch, q = _load(wh, _plays([late]), window=3)
    assert ch == set() and q["reproducao_id"].tolist() == [4]


def test_upsert_pela_chave_nao_duplica(tmp_path):
    wh = Warehouse(tmp_path)
    _load(wh, _plays())
    again = _plays()
    again.loc[0, "segundos_assistidos"] = 900          # correção do mesmo fato
    ch, _ = _load(wh, again)
    part = wh.read("reproducoes", {"2024-01"})
    assert ch == {"2024-01"} and len(part) == 1 and part["segundos_assistidos"].iloc[0] == 900
