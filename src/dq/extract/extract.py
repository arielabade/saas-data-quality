"""Extração do snapshot de referência (a "base limpa") a partir do MySQL.

Papel: ler as tabelas do escopo no MySQL e gravar um Parquet por tabela em data/source.
Entrada: MySQL carregado via docker compose (backend `mysql`) ou os Parquet do gerador
         (backend `parquet`, usado no CI, onde não há banco carregado).
Saída: data/source/<tabela>.parquet com os tipos do DDL e, no perfil `ci`, uma amostra de contas.
Dependências: sqlalchemy + pymysql (backend mysql), pandas.

A senha vem de MYSQL_PASSWORD no ambiente; nunca do código ou do YAML.
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

from dq.config import settings
from dq.io import write_table

# Tipos do DDL (schema.sql) que o driver não preserva sozinho.
INT_COLS = {
    "precos": ["plano_id"],
    "contas": ["indicada_por_conta_id"],
    "assinaturas": ["assinatura_anterior_id"],
    "assinatura_eventos": ["plano_anterior_id", "plano_novo_id"],
    "faturas": ["cupom_resgate_id"],
    "pagamentos": ["fatura_id"],
    "titulos": ["duracao_min"],
    "reproducoes": ["sessao_id", "episodio_id"],
}
DATE_COLS = {
    "precos": ["vigencia_inicio", "vigencia_fim"],
    "contas": ["data_nascimento"],
    "faturas": ["periodo_inicio", "periodo_fim", "vencimento_em"],
}


def _engine():
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL

    cfg = settings()["mysql"]
    pwd = os.environ.get("MYSQL_PASSWORD")
    if not pwd:
        raise SystemExit("MYSQL_PASSWORD não definida (rode `make env` ou exporte a variável)")
    url = URL.create("mysql+pymysql", username=cfg["user"], password=pwd, host=cfg["host"],
                     port=int(cfg["port"]), database=cfg["database"])
    return create_engine(url)


def _read_mysql(table: str, chunk: int) -> pd.DataFrame:
    eng = _engine()
    parts = list(pd.read_sql_table(table, eng, chunksize=chunk))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _read_parquet(table: str) -> pd.DataFrame:
    return pd.read_parquet(settings()["paths"]["generated"] / "parquet" / f"{table}.parquet")


def _fix_types(table: str, df: pd.DataFrame) -> pd.DataFrame:
    for c in INT_COLS.get(table, []):
        df[c] = pd.array(df[c], dtype="Int64")
    for c in DATE_COLS.get(table, []):
        df[c] = pd.to_datetime(df[c]).dt.date
    for c in df.columns:
        if df[c].dtype == object and df[c].map(type).isin([__import__("decimal").Decimal]).any():
            df[c] = df[c].astype(float)
        if str(df[c].dtype) in ("int8", "int16", "int32"):   # Parquet do gerador usa inteiros estreitos; MySQL, int64
            df[c] = df[c].astype("int64")
        if str(df[c].dtype).startswith("datetime64"):
            df[c] = df[c].astype("datetime64[s]")
    return df


def sample_accounts(tables: dict[str, pd.DataFrame], n: int, seed: int) -> dict[str, pd.DataFrame]:
    """Amostra n contas e mantém só as linhas ligadas a elas (catálogo e preços ficam inteiros)."""
    rng = np.random.default_rng(seed)
    contas = tables["contas"]
    keep = set(rng.choice(contas["conta_id"].to_numpy(), size=min(n, len(contas)), replace=False))
    out = dict(tables)
    out["contas"] = contas[contas["conta_id"].isin(keep)].copy()
    out["contas"]["indicada_por_conta_id"] = out["contas"]["indicada_por_conta_id"].where(
        out["contas"]["indicada_por_conta_id"].isin(keep))
    for t in ("perfis", "dispositivos", "assinaturas", "faturas", "pagamentos"):
        out[t] = tables[t][tables[t]["conta_id"].isin(keep)].copy()
    subs = set(out["assinaturas"]["assinatura_id"])
    out["assinatura_eventos"] = tables["assinatura_eventos"][tables["assinatura_eventos"]["assinatura_id"].isin(subs)].copy()
    perfis = set(out["perfis"]["perfil_id"])
    for t in ("sessoes_app", "reproducoes"):
        out[t] = tables[t][tables[t]["perfil_id"].isin(perfis)].copy()
    return out


def extract() -> None:
    cfg = settings()
    backend = cfg["extract"]["backend"]
    out = cfg["paths"]["source"]
    tables: dict[str, pd.DataFrame] = {}
    for t in cfg["extract"]["tables"]:
        t0 = time.time()
        df = _read_mysql(t, cfg["extract"]["chunk_rows"]) if backend == "mysql" else _read_parquet(t)
        tables[t] = _fix_types(t, df)
        print(f"[extract] {t:20s} {len(df):>10,d} linhas ({backend}, {time.time() - t0:.1f}s)")
    n = cfg["active_profile"].get("sample_contas")
    if n:
        tables = sample_accounts(tables, n, cfg["active_profile"].get("sample_seed", 0))
        print(f"[extract] perfil {cfg['profile']}: amostra de {n} contas")
    for t, df in tables.items():
        write_table(df.reset_index(drop=True), out, t)
    print(f"[extract] snapshot de referência em {out}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "generate":
        from dq.extract.generate import generate
        generate(force="--force" in sys.argv)
    else:
        extract()
