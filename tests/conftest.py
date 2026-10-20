"""Fixtures pequenas no formato da camada raw."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

T = pd.Timestamp


@pytest.fixture
def tiny_raw() -> dict[str, pd.DataFrame]:
    return {
        "contas": pd.DataFrame({"conta_id": [1], "email": [" Ana@Mail.example.com"], "uf": ["sp "]}),
        "dispositivos": pd.DataFrame({"dispositivo_id": [1, 2], "conta_id": [1, 1], "tipo": ["smartphone", "TV"]}),
        "precos": pd.DataFrame({"preco_id": [1], "valor_brl": [39.9], "vigencia_inicio": ["2023-01-01"], "vigencia_fim": [None]}),
        "faturas": pd.DataFrame({"fatura_id": [1], "valor_bruto": [39.9], "valor_desconto": [0.0], "valor_membro_extra": [0.0],
                                 "valor_total": [39.9], "periodo_inicio": ["2024-01-01"], "periodo_fim": ["2024-01-31"],
                                 "vencimento_em": ["2024-01-04"]}),
        "pagamentos": pd.DataFrame({"pagamento_id": [1], "valor_brl": [39.9]}),
        "perfis": pd.DataFrame({"perfil_id": [1], "conta_id": [1]}),
        "sessoes_app": pd.DataFrame({"sessao_id": [1], "perfil_id": [1], "dispositivo_id": [1],
                                     "inicio_em": ["2026-03-01T20:00:00Z"], "fim_em": ["2026-03-01T21:00:00Z"]}),
        "reproducoes": pd.DataFrame({"reproducao_id": [1, 2], "perfil_id": [1, 1], "dispositivo_id": [1, 2],
                                     "titulo_id": [1, 1], "episodio_id": pd.array([None, None], dtype="Int64"),
                                     "versao_app": ["6.1.0", "6.1.0"], "segundos_assistidos": [1_200_000, 1500],
                                     "inicio_em": ["2026-03-01T20:00:00Z", "2026-03-01 22:00:00"],
                                     "fim_em": ["2026-03-01T20:20:00Z", "2026-03-01 22:25:00"]}),
        "episodios": pd.DataFrame({"episodio_id": pd.Series([], dtype="int64"), "duracao_min": pd.Series([], dtype="int64")}),
        "titulos": pd.DataFrame({"titulo_id": [1], "duracao_min": [100]}),
    }


@pytest.fixture(scope="session")
def e2e_data(tmp_path_factory):
    """Perfil pequeno (amostra de contas) montado do zero numa pasta temporária:
    extração (backend parquet) -> perfil -> injeção de defeitos. Precisa de data/generated."""
    import os

    from dq.config import ROOT, settings

    gen = Path(os.environ.get("DQ_GENERATED_DIR", ROOT / "data" / "generated"))
    if not (gen / "parquet" / "reproducoes.parquet").exists():
        pytest.skip("base gerada ausente: rode `make generate` (precisa da pasta fonte)")
    base = tmp_path_factory.mktemp("e2e")
    env = {"DQ_DATA_DIR": str(base), "DQ_REPORTS_DIR": str(base / "reports"), "DQ_PROFILE": "ci",
           "DQ_EXTRACT_BACKEND": "parquet", "DQ_GENERATED_DIR": str(gen)}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    settings.cache_clear()
    from dq.corrupt import injector
    from dq.extract.extract import extract
    from dq.profile import profiler

    extract()
    profiler.run()
    injector.run()
    cfg = settings()
    yield {"base": base, "raw": cfg["paths"]["raw"], "raw_reference": cfg["paths"]["raw_reference"], "runs": cfg["paths"]["runs"]}
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    settings.cache_clear()
