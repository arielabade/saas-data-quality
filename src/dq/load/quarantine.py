"""Integridade referencial com quarentena.

Papel: nenhuma linha some em silêncio. O que não pode entrar na camada clean (pagamento de fatura
       inexistente, uso de perfil inexistente, assinatura duplicada, evento impossível, atraso fora
       da janela) vai para a quarentena com o motivo, para reprocessamento ou auditoria.
Entrada: tabelas em limpeza.
Saída: tabelas sem as linhas inválidas + DataFrame de quarentena (tabela, chave, motivo).
Dependências: pandas.

Decisão: reprodução cuja sessão não chegou (chave lógica, sem FK) NÃO vai para quarentena: o perfil
e o aparelho existem, e o perfil mostrou que sessões se perdem em falhas de pipeline. Fica sinalizada.
"""

from __future__ import annotations

import pandas as pd

from dq.clean import flags

COLUMNS = ["tabela", "chave", "motivo"]


def entries(table: str, keys, reason: str) -> pd.DataFrame:
    return pd.DataFrame({"tabela": table, "chave": pd.Series(keys, dtype="int64").to_numpy(), "motivo": reason})


def referential(t: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    q, fl = [], []
    pg = t["pagamentos"]
    bad = pg["fatura_id"].notna() & ~pg["fatura_id"].isin(t["faturas"]["fatura_id"])
    q.append(entries("pagamentos", pg.loc[bad, "pagamento_id"], "fatura_inexistente"))
    t["pagamentos"] = pg[~bad]
    fl.append(flags.make("orfao", "integridade_referencial", "pagamentos", pg.loc[bad, "pagamento_id"], "quarentena"))
    perfis = set(t["perfis"]["perfil_id"])
    for name, key in (("sessoes_app", "sessao_id"), ("reproducoes", "reproducao_id")):
        df = t[name]
        bad = ~df["perfil_id"].isin(perfis)
        q.append(entries(name, df.loc[bad, key], "perfil_inexistente"))
        fl.append(flags.make("orfao", "integridade_referencial", name, df.loc[bad, key], "quarentena"))
        t[name] = df[~bad]
    r = t["reproducoes"]
    lost = r["sessao_id"].notna() & ~r["sessao_id"].isin(t["sessoes_app"]["sessao_id"])
    fl.append(flags.make("sessao_nao_recebida", "chave_logica", "reproducoes", r.loc[lost, "reproducao_id"], "sinalizar"))
    return t, pd.concat(q, ignore_index=True), flags.concat(fl)


def drop_subscriptions(t: dict[str, pd.DataFrame], ids: pd.Series, reason: str) -> pd.DataFrame:
    """Tira assinaturas (e tudo que depende delas) da camada clean."""
    ids = set(ids)
    a, ev, f = t["assinaturas"], t["assinatura_eventos"], t["faturas"]
    fat = set(f.loc[f["assinatura_id"].isin(ids), "fatura_id"])
    pg = t["pagamentos"]
    q = [entries("assinaturas", a.loc[a["assinatura_id"].isin(ids), "assinatura_id"], reason),
         entries("assinatura_eventos", ev.loc[ev["assinatura_id"].isin(ids), "evento_id"], reason),
         entries("faturas", f.loc[f["fatura_id"].isin(fat), "fatura_id"], reason),
         entries("pagamentos", pg.loc[pg["fatura_id"].isin(fat), "pagamento_id"], reason)]
    t["assinaturas"] = a[~a["assinatura_id"].isin(ids)]
    t["assinatura_eventos"] = ev[~ev["assinatura_id"].isin(ids)]
    t["faturas"] = f[~f["fatura_id"].isin(fat)]
    t["pagamentos"] = pg[~pg["fatura_id"].isin(fat)]
    return pd.concat(q, ignore_index=True)
