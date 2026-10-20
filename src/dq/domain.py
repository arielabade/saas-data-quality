"""Conhecimento de domínio compartilhado (sem regra de limpeza e sem acesso ao registro de defeitos).

Papel: constantes e funções puras sobre o negócio da base fonte: tipos de dispositivo, fusos
       por UF, limites de plano e duração de conteúdo. Usado pelo injetor e pelo ETL.
Entrada/saída: DataFrames/Séries pandas.
Dependências: pandas, numpy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Variantes de texto encontradas no perfil (docs/DATA_SOURCE.md) -> valor canônico.
DEVICE_TYPE = {
    "tv": "tv", "smart tv": "tv",
    "celular": "celular", "smartphone": "celular", "mobile": "celular",
    "web": "web", "navegador": "web",
    "tablet": "tablet",
}
MOBILE = {"celular", "tablet"}

UF_NAMES = {
    "são paulo": "SP", "minas gerais": "MG", "rio de janeiro": "RJ", "espírito santo": "ES", "bahia": "BA",
    "pernambuco": "PE", "ceará": "CE", "maranhão": "MA", "paraíba": "PB", "rio grande do norte": "RN",
    "alagoas": "AL", "piauí": "PI", "sergipe": "SE", "paraná": "PR", "rio grande do sul": "RS",
    "santa catarina": "SC", "goiás": "GO", "distrito federal": "DF", "mato grosso": "MT",
    "mato grosso do sul": "MS", "pará": "PA", "amazonas": "AM", "rondônia": "RO", "tocantins": "TO",
    "amapá": "AP", "acre": "AC", "roraima": "RR",
}
UF_REGION = {
    **dict.fromkeys(["SP", "MG", "RJ", "ES"], "Sudeste"),
    **dict.fromkeys(["BA", "PE", "CE", "MA", "PB", "RN", "AL", "PI", "SE"], "Nordeste"),
    **dict.fromkeys(["PR", "RS", "SC"], "Sul"),
    **dict.fromkeys(["GO", "DF", "MT", "MS"], "Centro-Oeste"),
    **dict.fromkeys(["PA", "AM", "RO", "TO", "AP", "AC", "RR"], "Norte"),
}
# Fuso IANA por UF (sem horário de verão desde 2019).
UF_TZ = {
    **dict.fromkeys(["SP", "MG", "RJ", "ES", "BA", "PE", "CE", "MA", "PB", "RN", "AL", "PI", "SE",
                     "PR", "RS", "SC", "GO", "DF", "PA", "TO", "AP"], "America/Sao_Paulo"),
    **dict.fromkeys(["MT", "MS", "AM", "RO", "RR"], "America/Manaus"),
    "AC": "America/Rio_Branco",
}
TZ_OFFSET_H = {"America/Sao_Paulo": -3, "America/Manaus": -4, "America/Rio_Branco": -5}

QA_NETWORK = "10.250."          # rede interna de QA (vista no perfil)
HOLIDAYS = ["12-24", "12-25", "12-31", "01-01"]


def normalize_device_type(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.lower().map(DEVICE_TYPE).astype("string")


def normalize_uf(s: pd.Series) -> pd.Series:
    t = s.astype("string").str.strip()
    up = t.str.upper()
    ok = up.isin(list(UF_REGION))
    by_name = t.str.lower().map(UF_NAMES).astype("string")
    return up.where(ok, by_name).astype("string")


def content_seconds(plays: pd.DataFrame, episodios: pd.DataFrame, titulos: pd.DataFrame) -> pd.Series:
    """Duração do conteúdo de cada reprodução (episódio, ou filme), em segundos."""
    ep = plays["episodio_id"].map(episodios.set_index("episodio_id")["duracao_min"])
    fi = plays["titulo_id"].map(titulos.set_index("titulo_id")["duracao_min"])
    return (ep.astype(float).fillna(fi.astype(float)) * 60).rename("duracao_conteudo_seg")


def plan_screens(planos: pd.DataFrame) -> dict[int, int]:
    return planos.set_index("plano_id")["telas_simultaneas"].astype(int).to_dict()


def cpf_valid(cpf: pd.Series) -> pd.Series:
    """Valida os dígitos verificadores do CPF (vetorizado)."""
    d = cpf.astype("string").str.replace(r"\D", "", regex=True).fillna("")
    ok_len = (d.str.len() == 11).to_numpy()
    dd = d.where(ok_len, "00000000000")
    m = np.array([list(map(int, x)) for x in dd], dtype=int).reshape(-1, 11)
    s1 = (m[:, :9] * np.arange(10, 1, -1)).sum(1) * 10 % 11 % 10
    s2 = (m[:, :10] * np.arange(11, 1, -1)).sum(1) * 10 % 11 % 10
    same = (m == m[:, :1]).all(1)
    return pd.Series(ok_len & (s1 == m[:, 9]) & (s2 == m[:, 10]) & ~same, index=cpf.index)


def month_end(ts: pd.Series | pd.DatetimeIndex) -> pd.Series:
    return pd.to_datetime(ts).dt.to_period("M").dt.to_timestamp(how="end").dt.floor("s")
