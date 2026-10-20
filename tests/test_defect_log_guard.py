"""O código de limpeza NUNCA lê o registro de defeitos.

Duas barreiras:
1. estática: nenhum módulo fora de dq.corrupt e dq.evaluate cita o registro ou importa esses pacotes;
2. dinâmica: o ETL roda de ponta a ponta com qualquer leitura do registro transformada em erro.
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path

import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "dq"
ALLOWED = {"corrupt", "evaluate", "report"}  # report só lê resultados já agregados pelo evaluate
# o orquestrador importa o evaluate apenas dentro de main(), no comando `evaluate`, nunca no run_etl
ALLOWED_FUNCTIONS = {("pipeline.py", "main")}


def _etl_modules():
    for p in SRC.rglob("*.py"):
        if p.relative_to(SRC).parts[0] not in ALLOWED:
            yield p


def violations(source: str, filename: str = "x.py") -> list[str]:
    """Imports de dq.corrupt/dq.evaluate e strings de código (não docstrings) que citam o registro."""
    tree = ast.parse(source)
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, ast.Module | ast.FunctionDef | ast.ClassDef) and n.body
                  and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    allowed_nodes = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and (filename, n.name) in ALLOWED_FUNCTIONS:
            allowed_nodes |= {id(x) for x in ast.walk(n)}
    out = []
    for n in ast.walk(tree):
        if id(n) in allowed_nodes:
            continue
        mods = []
        if isinstance(n, ast.ImportFrom) and n.module:
            mods = [n.module]
        elif isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        out += [f"linha {n.lineno}: import {m}" for m in mods if m.startswith(("dq.corrupt", "dq.evaluate"))]
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings and "defect_log" in n.value:
            out.append(f"linha {n.lineno}: string '{n.value}'")
        if isinstance(n, ast.Name | ast.Attribute) and getattr(n, "id", getattr(n, "attr", "")) == "DefectLog":
            out.append(f"linha {n.lineno}: DefectLog")
    return out


def test_nenhum_modulo_de_limpeza_cita_o_registro():
    offenders = [f"{p.relative_to(SRC)} {v}" for p in _etl_modules() for v in violations(p.read_text(), p.name)]
    assert not offenders, "módulos do ETL citam o registro de defeitos:\n" + "\n".join(offenders)


def test_a_regra_estatica_pegaria_uma_leitura():
    """Garante que o teste acima não passa por vacuidade."""
    assert violations('import pandas as pd\nx = pd.read_parquet(cfg["paths"]["defect_log"])')
    assert violations("from dq.corrupt.log import DefectLog")
    assert violations("def run_etl():\n    from dq.evaluate.detection import load_defect_log", "pipeline.py")
    assert not violations('"""Este módulo não lê o defect_log."""\nx = 1')


@pytest.fixture
def block_defect_log(monkeypatch):
    def guard(path):
        if "defect_log" in str(path):
            raise AssertionError(f"o ETL tentou ler o registro de defeitos: {path}")

    real_open, real_read = builtins.open, pd.read_parquet

    def g_open(file, *a, **k):
        guard(file)
        return real_open(file, *a, **k)

    def g_read(path, *a, **k):
        guard(path)
        return real_read(path, *a, **k)

    monkeypatch.setattr(builtins, "open", g_open)
    monkeypatch.setattr(pd, "read_parquet", g_read)
    return guard


def test_a_barreira_dinamica_funciona(block_defect_log, tmp_path):
    p = tmp_path / "defect_log"
    p.mkdir()
    with pytest.raises(AssertionError):
        pd.read_parquet(p / "defect_log.parquet")


@pytest.mark.e2e
def test_etl_completo_sem_tocar_no_registro(block_defect_log, e2e_data):
    """Roda o ETL no perfil pequeno com qualquer leitura do registro proibida."""
    from dq.pipeline import run_etl

    rep = run_etl(e2e_data["raw"], e2e_data["runs"] / "guard", verbose=False)
    assert rep["linhas"]["clean"]["reproducoes"] > 0
