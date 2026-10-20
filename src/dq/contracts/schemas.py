"""Contratos de dados por camada (pandera).

Papel: dizer, por camada, o que cada tabela PROMETE. O raw promete pouco (estrutura); o staging
       promete tipos e unidades; o clean promete as regras de negócio; os marts prometem métricas
       coerentes. Falha no raw é esperada e só é contada; falha no clean ou nos marts para a execução.
Entrada: dicionário de DataFrames de uma camada.
Saída: lista de resultados (camada, tabela, verificação, falhas) para o relatório de qualidade.
Dependências: pandera.
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera import Check, Column

TS = "datetime64[ms]"


def _ts(nullable: bool = False, **kw) -> Column:
    return Column(TS, nullable=nullable, coerce=True, **kw)


RAW = {
    "pagamentos": pa.DataFrameSchema({
        "pagamento_id": Column(int, unique=True),
        "valor_brl": Column(float),
        "status": Column(str, Check.isin(["aprovado", "recusado", "expirado", "contestado", "processado"])),
    }, strict=False),
    "reproducoes": pa.DataFrameSchema({
        "reproducao_id": Column(int, unique=True),
        "inicio_em": Column(str, Check.str_matches(r"^\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d")),
        "segundos_assistidos": Column(int, Check.ge(0, error="tempo assistido negativo")),
        "recebido_em": _ts(),
    }, strict=False),
    "contas": pa.DataFrameSchema({
        "conta_id": Column(int, unique=True),
        "uf": Column(str, Check.str_matches(r"^[A-Z]{2}$"), nullable=False),
    }, strict=False),
}

STAGING = {
    "faturas": pa.DataFrameSchema({
        "fatura_id": Column(int, unique=True),
        "bruto_centavos": Column("Int64", Check.ge(0)),
        "total_centavos": Column("Int64", Check.ge(0)),
        "moeda": Column(str, Check.eq("BRL")),
    }, strict=False),
    "pagamentos": pa.DataFrameSchema({
        "valor_centavos": Column("Int64"),
        "moeda": Column(str, Check.eq("BRL")),
    }, strict=False),
    "reproducoes": pa.DataFrameSchema({
        "inicio_em": _ts(),
        "tipo_dispositivo": Column(str, Check.isin(["tv", "celular", "web", "tablet"]), nullable=True),
        "segundos_assistidos": Column(int),
    }, strict=False),
    "dispositivos": pa.DataFrameSchema({
        "tipo": Column(str, Check.isin(["tv", "celular", "web", "tablet"])),
    }, strict=False),
}

CLEAN = {
    "pagamentos": pa.DataFrameSchema({
        "pagamento_id": Column(int, unique=True),
        "valor_centavos": Column("Int64"),
    }, strict=False),
    "reproducoes": pa.DataFrameSchema({
        "reproducao_id": Column(int, unique=True),
        "inicio_em": _ts(checks=[Check.ge(pd.Timestamp("2023-01-01"), error="data impossível")]),
        "segundos_assistidos": Column(int, Check.ge(0)),
    }, checks=[
        Check(lambda d: (d["duracao_conteudo_seg"].isna()
                         | (d["segundos_assistidos"] <= d["duracao_conteudo_seg"] * 1.05 + 1)), error="assistido > duração"),
    ], strict=False),
    "timeline": pa.DataFrameSchema({
        "estado": Column(str, Check.isin(["trial", "ativo", "inadimplente", "cancelamento_agendado"])),
    }, checks=[Check(lambda d: d["fim"] >= d["inicio"], error="intervalo invertido")], strict=False),
}

MARTS = {
    "mrr": pa.DataFrameSchema({
        "mrr_centavos": Column(int, Check.ge(0)),
    }, strict=False),
    "assinantes": pa.DataFrameSchema({
        "ativos_fim": Column(int, Check.ge(0)),
        "taxa_churn": Column(float, Check.in_range(0, 1), nullable=True),
    }, strict=False),
    "engajamento": pa.DataFrameSchema({
        "horas_por_assinante": Column(float, Check.in_range(0, 24 * 31 * 5), nullable=True),
    }, strict=False),
}

LAYERS = {"raw": RAW, "staging": STAGING, "clean": CLEAN, "marts": MARTS}
BLOCKING = {"clean", "marts"}


class ContractError(RuntimeError):
    pass


def validate(layer: str, tables: dict[str, pd.DataFrame], raise_on_fail: bool | None = None) -> list[dict]:
    raise_on_fail = layer in BLOCKING if raise_on_fail is None else raise_on_fail
    results = []
    for name, schema in LAYERS[layer].items():
        if name not in tables or tables[name] is None or not len(tables[name]):
            continue
        try:
            schema.validate(tables[name], lazy=True)
            results.append({"camada": layer, "tabela": name, "verificacao": "todas", "falhas": 0})
        except pa.errors.SchemaErrors as err:
            fc = err.failure_cases
            for check, g in fc.groupby(fc["check"].astype(str)):
                col = g["column"].dropna().astype(str).iloc[0] if g["column"].notna().any() else ""
                results.append({"camada": layer, "tabela": name, "verificacao": f"{col}: {check}".strip(": "), "falhas": len(g)})
    failed = [r for r in results if r["falhas"]]
    if raise_on_fail and failed:
        raise ContractError(f"contrato da camada {layer} violado: {failed}")
    return results
