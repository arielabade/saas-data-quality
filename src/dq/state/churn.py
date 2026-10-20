"""Definição de churn usada no projeto (texto completo em docs/METRICS.md).

Papel: transformar a linha do tempo das assinaturas em períodos vigentes por CONTA e eventos de
       churn tipados (voluntário, involuntário), com período de carência para reativação.
Entrada: intervalos da máquina de estados (state.machine.build_timeline).
Saída: spans por conta (inicio, fim, tipo_fim) e eventos de churn.
Dependências: pandas.

- Conta vigente: tem assinatura em trial, ativo, inadimplente ou cancelamento agendado.
- Churn: a conta deixa de ter assinatura vigente. Voluntário se o último estado era
  cancelamento agendado; involuntário se era inadimplente (falha de pagamento após as
  retentativas); "outro" nos demais casos.
- Carência: se a conta volta a ter assinatura vigente em até 7 dias, os períodos são unidos e não
  há churn (troca de cartão, pausa curta). A inadimplência em si NÃO é churn: é período de carência
  do pagamento.
"""

from __future__ import annotations

import pandas as pd

from dq.state.machine import END_OF_DATA


def account_spans(tl: pd.DataFrame, vigentes: list[str], grace_days: int) -> pd.DataFrame:
    v = tl[tl["estado"].isin(vigentes)].sort_values(["conta_id", "inicio"])
    rows = []
    grace = pd.Timedelta(days=grace_days)
    for conta, g in v.groupby("conta_id", sort=False):
        cur_s, cur_e, last_state = None, None, None
        for r in g.itertuples():
            if cur_s is None:
                cur_s, cur_e, last_state = r.inicio, r.fim, r.estado
            elif r.inicio <= cur_e + grace:
                if r.fim >= cur_e:
                    cur_e, last_state = r.fim, r.estado
            else:
                rows.append((conta, cur_s, cur_e, last_state))
                cur_s, cur_e, last_state = r.inicio, r.fim, r.estado
        rows.append((conta, cur_s, cur_e, last_state))
    sp = pd.DataFrame(rows, columns=["conta_id", "inicio", "fim", "ultimo_estado"])
    sp["churn"] = sp["fim"] < END_OF_DATA
    sp["tipo_churn"] = sp["ultimo_estado"].map({"cancelamento_agendado": "voluntario", "inadimplente": "involuntario"}).fillna("outro")
    sp.loc[~sp["churn"], "tipo_churn"] = None
    return sp
