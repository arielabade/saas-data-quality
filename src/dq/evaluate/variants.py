"""Variantes do ETL usadas na avaliação.

Papel: rodar o mesmo ETL em configurações diferentes para isolar o efeito de cada decisão:
       - verdade: base de referência (sem defeitos) com todas as regras;
       - ingenua: base suja, nenhuma regra (só padronização de formato);
       - limpa: base suja, todas as regras (reaproveita a execução de `make etl`, data/runs/limpo);
       - sem_<regra>: base suja, todas as regras menos uma (custo de não aplicá-la);
       - outlier_como_erro: remove perfil-dias marcados por IQR (decisão errada, para comparação);
       - janela_0: atrasados fora do lote vão para a quarentena.
Entrada: data/raw, data/raw_reference.
Saída: data/runs/<variante>/...
Dependências: dq.pipeline.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor

from dq.config import load_yaml, settings

ABLATIONS = ["contas_internas", "bots", "quarentena_orfaos", "dedup_pagamentos", "dedup_uso", "fuso_e_relogio",
             "unificar_dispositivos", "limites_fisicos", "maquina_estados", "sobreposicao_assinaturas", "preco_scd"]


def variant_specs() -> dict[str, dict]:
    rules = load_yaml("cleaning")["regras"]
    off = {k: False for k in rules}
    specs = {
        "verdade": {"raw": "raw_reference"},
        "ingenua": {"raw": "raw", "rules": off},
        "outlier_como_erro": {"raw": "raw", "rules": {"outlier_como_erro": True}},
        "janela_0": {"raw": "raw", "overrides": {"carga": {"janela_atrasados_dias": 0}}},
    }
    for a in ABLATIONS:
        specs[f"sem_{a}"] = {"raw": "raw", "rules": {a: False}}
    return specs


def _run(name: str, spec: dict) -> tuple[str, dict]:
    from dq.pipeline import run_etl

    cfg = settings()
    run_dir = cfg["paths"]["runs"] / "variantes" / name
    rep = run_etl(cfg["paths"][spec["raw"]], run_dir, rules=spec.get("rules"), overrides=spec.get("overrides"),
                  persist_staging=name in ("verdade",), strict_contracts=False, verbose=True)
    return name, rep


def run_all(names: list[str] | None = None, workers: int | None = None) -> dict[str, dict]:
    specs = variant_specs()
    names = names or list(specs)
    workers = workers or int(os.environ.get("DQ_WORKERS", "2"))
    out = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for name, rep in ex.map(_run, names, [specs[n] for n in names]):
            out[name] = rep
    return out


def run_dir(name: str):
    cfg = settings()
    return cfg["paths"]["runs"] / "limpo" if name == "limpa" else cfg["paths"]["runs"] / "variantes" / name
