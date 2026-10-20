"""Tabela de preços com histórico (SCD tipo 2) e conferência do preço de cada fatura.

Papel: garantir que o preço usado em cada fatura seja o VIGENTE na data do período cobrado.
Entrada: precos (staging), faturas e pagamentos (staging).
Saída: dim_preco (uma linha por versão de preço, com valido_de/valido_ate/atual) e faturas e
       pagamentos corrigidos + flags.
Dependências: pandas.

Decisão: a fatura com preço de tabela antiga é CORRIGIDA para o preço vigente (o contrato é a
tabela de preços; a divergência é cache de preço vencido no faturamento). O pagamento que
registrou o valor da fatura errada acompanha a correção. Alternativa descartada: manter o valor
cobrado e só sinalizar (ver docs/DECISIONS.md).
"""

from __future__ import annotations

import pandas as pd

from dq.clean import flags

OPEN_END = pd.Timestamp("2262-01-01")


def build_price_scd(precos: pd.DataFrame) -> pd.DataFrame:
    p = precos.copy()
    p["plano_id"] = p["plano_id"].astype("Int64")
    p = p.sort_values(["item", "plano_id", "periodicidade", "vigencia_inicio"])
    grp = p.groupby(["item", "plano_id", "periodicidade"], dropna=False)
    p["versao"] = grp.cumcount() + 1
    nxt = grp["vigencia_inicio"].shift(-1)
    # valido_ate é exclusivo; vem da próxima versão (não confia em vigencia_fim, que pode ter buraco)
    p["valido_de"] = p["vigencia_inicio"]
    p["valido_ate"] = nxt.fillna(OPEN_END)
    p["atual"] = nxt.isna()
    return p[["preco_id", "item", "plano_id", "periodicidade", "versao", "valido_de", "valido_ate", "atual",
              "valor_centavos", "moeda"]].reset_index(drop=True)


def price_at(scd: pd.DataFrame, plano: pd.Series, periodicidade: pd.Series, when: pd.Series) -> pd.DataFrame:
    """Versão de preço vigente para cada (plano, periodicidade, data)."""
    q = pd.DataFrame({"plano_id": plano.astype("Int64").to_numpy(), "periodicidade": periodicidade.to_numpy(),
                      "quando": pd.to_datetime(when).to_numpy(), "_i": range(len(plano))})
    s = scd[scd["item"] == "assinatura"]
    m = q.merge(s, on=["plano_id", "periodicidade"], how="left")
    m = m[(m["valido_de"] <= m["quando"]) & (m["quando"] < m["valido_ate"])]
    return m.set_index("_i").reindex(range(len(plano)))[["preco_id", "valor_centavos"]]


def check_invoices(faturas: pd.DataFrame, pagamentos: pd.DataFrame, scd: pd.DataFrame
                   ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    f = faturas.copy()
    pid = scd.set_index("preco_id")
    plano = f["preco_id"].map(pid["plano_id"])
    per = f["preco_id"].map(pid["periodicidade"])
    exp = price_at(scd, plano, per, f["periodo_inicio"])
    exp.index = f.index
    wrong = exp["preco_id"].notna() & (f["preco_id"] != exp["preco_id"]) & (f["bruto_centavos"] != exp["valor_centavos"])
    old_total = f.loc[wrong, "total_centavos"].copy()
    f.loc[wrong, "preco_id"] = exp.loc[wrong, "preco_id"].astype("int64")
    f.loc[wrong, "bruto_centavos"] = exp.loc[wrong, "valor_centavos"]
    f.loc[wrong, "total_centavos"] = (f.loc[wrong, "bruto_centavos"] - f.loc[wrong, "desconto_centavos"]
                                      + f.loc[wrong, "membro_extra_centavos"]).clip(lower=0)
    g = pagamentos.copy()
    fix = pd.DataFrame({"fatura_id": f.loc[wrong, "fatura_id"], "velho": old_total, "novo": f.loc[wrong, "total_centavos"]})
    m = g.merge(fix, on="fatura_id", how="left")
    hit = (m["tipo"] == "cobranca").to_numpy() & (m["valor_centavos"] == m["velho"]).fillna(False).to_numpy()
    g.loc[hit, "valor_centavos"] = m.loc[hit, "novo"].to_numpy()
    fl = flags.concat([
        flags.make("preco_divergente", "scd2_vigente_na_data", "faturas", f.loc[wrong, "fatura_id"], "corrigir"),
        flags.make("preco_divergente", "scd2_vigente_na_data", "pagamentos", g.loc[hit, "pagamento_id"], "corrigir"),
    ])
    return f, g, fl
