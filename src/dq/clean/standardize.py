"""Camada staging: tipagem e padronização (nenhuma regra de negócio ainda).

Papel: transformar o raw no formato canônico do projeto:
       - datas e horas em UTC no armazenamento (`*_em` como datetime UTC sem fuso);
       - valores monetários em centavos inteiros (`*_centavos`) com moeda explícita;
       - textos canônicos (tipo de dispositivo, UF) e região derivada da UF;
       - correções de FORMATO já documentadas no perfil (app 6.x móvel grava milissegundos).
       Registros ambíguos não são "adivinhados" aqui: ficam marcados para as regras de clean
       (ex.: `ts_sem_fuso` para hora do web sem offset).
Entrada: tabelas raw (data/raw ou data/raw_reference).
Saída: dicionário de DataFrames staging + contadores do que foi padronizado.
Dependências: pandas, numpy, dq.domain.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dq.domain import MOBILE, UF_REGION, content_seconds, normalize_device_type, normalize_uf

CURRENCY = "BRL"


def to_cents(x: pd.Series) -> pd.Series:
    """BRL decimal -> centavos inteiros (arredondamento comercial, sem erro de ponto flutuante)."""
    return pd.array(np.round(x.astype(float) * 100), dtype="Int64")


def parse_client_ts(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Texto do cliente -> UTC. Retorna (timestamp UTC sem tz, marca de 'sem fuso ambíguo').

    Formatos aceitos (ver docs/DATA_SOURCE.md):
      'AAAA-MM-DDTHH:MM:SSZ'        celular/tablet, UTC
      'AAAA-MM-DDTHH:MM:SS-03:00'   web, hora local com offset
      'AAAA-MM-DD HH:MM:SS'         TV, UTC por contrato
      'AAAA-MM-DDTHH:MM:SS'         sem offset e fora do contrato: ambíguo, lido como UTC e marcado
    """
    txt = s.astype("string")
    ambiguous = txt.str.contains("T", regex=False).fillna(False) & ~txt.str.contains(r"(?:Z|[+-]\d\d:\d\d)$", regex=True).fillna(False)
    # Cada grupo é lido separado: num parse único, o pandas aplica o offset de umas linhas às
    # linhas sem fuso (bug real que deslocou a TV em +3 h na primeira versão deste pipeline).
    has_tz = txt.str.contains(r"(?:Z|[+-]\d\d:\d\d)$", regex=True).fillna(False)
    ts = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ms]")
    if has_tz.any():
        ts[has_tz] = pd.to_datetime(txt[has_tz], format="ISO8601", utc=True, errors="coerce").dt.tz_localize(None).astype("datetime64[ms]")
    naive = ~has_tz & txt.notna()
    if naive.any():
        ts[naive] = pd.to_datetime(txt[naive], format="ISO8601", errors="coerce").astype("datetime64[ms]")
    return ts, ambiguous.astype(bool)


def standardize(raw: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict]:
    t = {k: v.copy() for k, v in raw.items()}
    stats: dict[str, int] = {}

    c = t["contas"]
    c["email"] = c["email"].astype("string").str.strip().str.lower()
    uf = normalize_uf(c["uf"])
    stats["uf_padronizada"] = int((uf.fillna("") != c["uf"].astype("string").fillna("")).sum())
    c["uf"] = uf
    c["regiao"] = uf.map(UF_REGION).astype("string")

    d = t["dispositivos"]
    tipo = normalize_device_type(d["tipo"])
    stats["tipo_dispositivo_padronizado"] = int((tipo != d["tipo"].astype("string")).sum())
    d["tipo"] = tipo

    p = t["precos"]
    p["valor_centavos"] = to_cents(p["valor_brl"])
    p["moeda"] = CURRENCY
    for col in ("vigencia_inicio", "vigencia_fim"):
        p[col] = pd.to_datetime(p[col])

    f = t["faturas"]
    for col in ("valor_bruto", "valor_desconto", "valor_membro_extra", "valor_total"):
        f[col.replace("valor_", "") + "_centavos"] = to_cents(f[col])
    f["moeda"] = CURRENCY
    for col in ("periodo_inicio", "periodo_fim", "vencimento_em"):
        f[col] = pd.to_datetime(f[col])
    f = f.drop(columns=["valor_bruto", "valor_desconto", "valor_membro_extra", "valor_total"])
    t["faturas"] = f

    g = t["pagamentos"]
    g["valor_centavos"] = to_cents(g["valor_brl"])
    g["moeda"] = CURRENCY
    t["pagamentos"] = g.drop(columns=["valor_brl"])

    perfil_conta = t["perfis"].set_index("perfil_id")["conta_id"]
    dev_tipo = d.set_index("dispositivo_id")["tipo"]
    for name in ("sessoes_app", "reproducoes"):
        df = t[name]
        ts_i, amb_i = parse_client_ts(df["inicio_em"])
        ts_f, amb_f = parse_client_ts(df["fim_em"])
        df["inicio_em"], df["fim_em"] = ts_i, ts_f
        df["ts_sem_fuso"] = amb_i | amb_f
        df["conta_id"] = pd.array(df["perfil_id"].map(perfil_conta), dtype="Int64")
        df["tipo_dispositivo"] = df["dispositivo_id"].map(dev_tipo).astype("string")
        stats[f"{name}_ts_sem_fuso"] = int(df["ts_sem_fuso"].sum())

    r = t["reproducoes"]
    # Unidade: o app 6.x em celular/tablet grava milissegundos (achado do perfil). É formato, não erro.
    ms = r["versao_app"].astype("string").str.startswith("6.").fillna(False) & r["tipo_dispositivo"].isin(list(MOBILE))
    r["segundos_assistidos"] = np.where(ms, np.round(r["segundos_assistidos"] / 1000), r["segundos_assistidos"]).astype("int64")
    r["unidade_ms_convertida"] = ms.to_numpy()
    stats["reproducoes_ms_convertidas"] = int(ms.sum())
    r["duracao_conteudo_seg"] = content_seconds(r, t["episodios"], t["titulos"])
    return t, stats
