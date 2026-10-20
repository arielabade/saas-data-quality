"""Leitura de configuração (YAML + variáveis de ambiente).

Papel: único ponto que resolve caminhos, perfis e parâmetros do projeto.
Entrada: config/*.yaml, variáveis de ambiente e, se existir, o arquivo .env da raiz.
Saída: dicionários de configuração com `${VAR:-padrão}` já expandidos e caminhos absolutos.
Dependências: pyyaml.

Credenciais nunca passam por aqui: a senha do MySQL é lida do ambiente na hora da conexão.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
_VAR = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def _load_dotenv() -> None:
    """Carrega .env da raiz sem sobrescrever variáveis já definidas no ambiente."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        out = _VAR.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
        # YAML já tipou o literal; aqui só convertemos o que veio de variável
        if out != value:
            if out.isdigit():
                return int(out)
            if out.lower() in ("null", "none", ""):
                return None
        return out
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def load_yaml(name: str) -> dict:
    """Lê config/<name>.yaml expandindo variáveis de ambiente."""
    _load_dotenv()
    with open(ROOT / "config" / f"{name}.yaml", encoding="utf-8") as f:
        return _expand(yaml.safe_load(f))


@lru_cache(maxsize=1)
def settings() -> dict:
    """Configuração principal com caminhos resolvidos em relação à raiz do repositório."""
    cfg = load_yaml("settings")
    cfg["paths"] = {k: resolve(v) for k, v in cfg["paths"].items()}
    cfg["source"]["dir"] = resolve(cfg["source"]["dir"])
    cfg["active_profile"] = cfg["profiles"][cfg["profile"]]
    return cfg


def resolve(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p).resolve()
