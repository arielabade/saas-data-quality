"""Nulos: primeiro o mecanismo, depois (talvez) a imputação.

Papel: para cada coluna com nulos, testar se a ausência depende de algo observado
       (canal de aquisição, primeiro aparelho, plano). Sem dependência: compatível com MCAR.
       Com dependência: MAR (a imputação ingênua pela média/moda geral enviesaria o grupo).
       MNAR não é testável com os dados; fica registrado como hipótese a descartar.
Entrada: contas, dispositivos, assinaturas, sessoes_app (staging).
Saída: tabela de mecanismo por coluna; contas com `regiao` imputada (+ flags `imputar`).
Dependências: pandas, numpy, scipy.

Decisões:
- UF nula concentrada em cadastro pela TV (MAR): não se imputa UF (não há como saber o estado);
  imputa-se a REGIÃO pela região mais frequente das sessões da própria conta, que é observada.
  Sem sessões com região, fica nula e a conta usa o fuso padrão do país.
- telefone, data de nascimento e CEP: compatíveis com MCAR e fora das métricas: não se imputa,
  só se mede. Imputar idade criaria um perfil etário que ninguém informou.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

from dq.clean import flags


def cramers_v(table: pd.DataFrame) -> tuple[float, float]:
    if table.shape[0] < 2 or table.shape[1] < 2:
        return 0.0, 1.0
    chi2, p, _, _ = chi2_contingency(table)
    n = table.to_numpy().sum()
    return float(np.sqrt(chi2 / (n * (min(table.shape) - 1)))), float(p)


def mechanism_report(contas: pd.DataFrame, dispositivos: pd.DataFrame, assinaturas: pd.DataFrame,
                     columns: tuple[str, ...] = ("uf", "telefone", "data_nascimento", "cep")) -> pd.DataFrame:
    first_dev = dispositivos.sort_values(["conta_id", "registrado_em"]).drop_duplicates("conta_id").set_index("conta_id")["tipo"]
    plano = assinaturas.sort_values("iniciada_em").drop_duplicates("conta_id").set_index("conta_id")["plano_id"]
    ctx = pd.DataFrame({
        "canal_aquisicao": contas["canal_aquisicao_id"].astype(str).to_numpy(),
        "primeiro_aparelho": contas["conta_id"].map(first_dev).fillna("nenhum").astype(str).to_numpy(),
        "plano_inicial": contas["conta_id"].map(plano).fillna(0).astype(int).astype(str).to_numpy(),
    })
    rows = []
    for col in columns:
        miss = contas[col].isna().to_numpy()
        row = {"coluna": col, "pct_nulos": round(100 * miss.mean(), 2)}
        best = ("", 0.0, 1.0)
        for var in ctx.columns:
            v, p = cramers_v(pd.crosstab(ctx[var], miss))
            row[f"v_{var}"], row[f"p_{var}"] = round(v, 3), p
            if v > best[1]:
                best = (var, v, p)
        # V >= 0,1 com p < 0,001: a ausência depende de algo observado
        row["mecanismo"] = "MAR" if best[1] >= 0.1 and best[2] < 1e-3 else "compatível com MCAR"
        row["depende_de"] = best[0] if row["mecanismo"] == "MAR" else ""
        if row["mecanismo"] == "MAR":
            grp = pd.Series(miss).groupby(ctx[best[0]]).mean().sort_values(ascending=False)
            row["grupo_mais_afetado"] = f"{grp.index[0]} ({100 * grp.iloc[0]:.0f}% nulo vs {100 * miss.mean():.0f}% geral)"
        rows.append(row)
    return pd.DataFrame(rows)


def impute_region(contas: pd.DataFrame, sessoes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    c = contas.copy()
    need = c["regiao"].isna()
    s = sessoes.dropna(subset=["regiao", "conta_id"])
    mode = s.groupby("conta_id")["regiao"].agg(lambda x: x.value_counts().index[0])
    fill = c.loc[need, "conta_id"].map(mode)
    c["regiao_imputada"] = False
    ok = fill.notna()
    c.loc[fill[ok].index, "regiao"] = fill[ok]
    c.loc[fill[ok].index, "regiao_imputada"] = True
    f = flags.make("regiao_imputada", "moda_das_sessoes_da_conta", "contas", c.loc[fill[ok].index, "conta_id"], "imputar",
                   fill[ok].to_numpy())
    return c, f
