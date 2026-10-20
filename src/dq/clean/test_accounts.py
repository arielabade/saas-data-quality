"""Contas internas, de QA e de teste misturadas com clientes.

Papel: identificar contas que não são clientes para tirá-las de MRR, base ativa, churn e engajamento.
Entrada: contas (staging) e sessoes_app (para a rede de QA).
Saída: DataFrame (conta_id, motivo) e flags com ação `excluir_das_metricas`.
Dependências: pandas, dq.domain.

Decisão de negócio: a conta NÃO é apagada (o financeiro precisa reconciliar cobranças de teste);
ela fica na camada clean com a marca e sai das métricas. Qualquer sinal basta, porque o custo
de manter um teste nas métricas (MRR e engajamento inflados) é maior que o de excluir um cliente
com nome "Teste" — e esse caso é raríssimo.
"""

from __future__ import annotations

import pandas as pd

from dq.clean import flags
from dq.domain import QA_NETWORK, cpf_valid

EMAIL_PATTERN = r"(?:^|[._+\-])(?:qa|teste|test|homolog|automacao|dummy)(?:[._+\-@\d]|$)"
NAME_PATTERN = r"\b(?:teste|qa|homologa[cç][aã]o)\b"


def detect(contas: pd.DataFrame, sessoes: pd.DataFrame, qa_share: float = 0.5) -> pd.DataFrame:
    c = contas
    email = c["email"].astype("string").str.lower()
    signals = {
        "dominio_interno": email.str.endswith("@cinelume.example").fillna(False),
        "email_de_teste": email.str.contains(EMAIL_PATTERN, regex=True).fillna(False),
        "nome_de_teste": c["nome_titular"].astype("string").str.lower().str.contains(NAME_PATTERN, regex=True).fillna(False),
        "cpf_invalido": ~cpf_valid(c["cpf"]),
    }
    # CPF repetido: a conta mais nova é a cópia (o cliente real cadastrou primeiro)
    order = c.sort_values(["criada_em", "conta_id"])
    dup = order.duplicated("cpf", keep="first")
    signals["cpf_duplicado"] = dup.reindex(c.index).fillna(False)
    s = sessoes[["conta_id", "ip"]].dropna(subset=["conta_id"])
    share = s["ip"].astype("string").str.startswith(QA_NETWORK).groupby(s["conta_id"]).mean()
    signals["rede_qa"] = c["conta_id"].map(share).fillna(0) >= qa_share
    sig = pd.DataFrame(signals)
    hit = sig.any(axis=1)
    motivo = sig[hit].apply(lambda r: "+".join(k for k, v in r.items() if v), axis=1)
    return pd.DataFrame({"conta_id": c.loc[hit, "conta_id"].to_numpy(), "motivo": motivo.to_numpy()})


def to_flags(found: pd.DataFrame) -> pd.DataFrame:
    return flags.make("conta_interna", "regras_de_cadastro", "contas", found["conta_id"], "excluir_das_metricas", found["motivo"])
