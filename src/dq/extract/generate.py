"""Geração da base fonte sem tocar na pasta original.

Papel: rodar o gerador da base fonte (`gerar_dados.py`) apontando a saída para data/generated.
Entrada: pasta da fonte (DQ_SOURCE_DIR), escala e semente de config/settings.yaml.
Saída: data/generated/{parquet,csv}/<tabela>.* (só as tabelas do escopo são mantidas).
Dependências: a própria fonte (numpy, pandas, pyarrow, faker).

Decisões:
- A fonte é somente leitura: o gerador roda com `-B` (sem __pycache__) e com `--saida` e
  `--gabarito` fora dela. O gabarito vai para uma pasta temporária e é apagado em seguida:
  este projeto não usa gabarito em nenhuma etapa.
- Tabelas fora do escopo (eventos de interface, heartbeats, marketing...) são descartadas
  para caber no disco e na memória; ver docs/DECISIONS.md.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

from dq.config import settings


def generate(force: bool = False) -> None:
    cfg = settings()
    src = cfg["source"]["dir"]
    out = cfg["paths"]["generated"]
    keep = set(cfg["extract"]["tables"])
    if not (src / "gerar_dados.py").exists():
        raise SystemExit(f"base fonte não encontrada em {src} (ajuste DQ_SOURCE_DIR)")
    if (out / "parquet" / "reproducoes.parquet").exists() and not force:
        print(f"[data] {out} já existe; use --force para regerar")
        _prune(out, keep)
        return
    gab = tempfile.mkdtemp(prefix="gabarito_descartado_")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    cmd = [sys.executable, "-B", str(src / "gerar_dados.py"), "--scale", cfg["source"]["scale"],
           "--seed", str(cfg["source"]["seed"]), "--saida", str(out), "--gabarito", gab]
    print("[data] gerando:", " ".join(cmd[2:]))
    try:
        subprocess.run(cmd, check=True, env=env, cwd=tempfile.gettempdir())
    finally:
        shutil.rmtree(gab, ignore_errors=True)
    _prune(out, keep)
    print(f"[data] base gerada em {out} ({len(keep)} tabelas mantidas)")


def _prune(out, keep: set[str]) -> None:
    """Remove as tabelas fora do escopo (só da cópia gerada; a fonte não é tocada)."""
    for sub, ext in (("parquet", ".parquet"), ("csv", ".csv.gz")):
        for f in (out / sub).iterdir():
            if f.name.removesuffix(ext) not in keep:
                f.unlink()


if __name__ == "__main__":
    generate(force="--force" in sys.argv)
