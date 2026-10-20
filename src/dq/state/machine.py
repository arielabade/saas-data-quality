"""Linha do tempo de cada assinatura como máquina de estados.

Papel: reconstruir, a partir dos eventos, em que estado cada assinatura estava em cada instante
       (teste -> ativo -> inadimplente -> cancelamento agendado -> cancelado; a reativação é uma
       assinatura nova ligada à anterior), com regras explícitas para transições inválidas.
Entrada: assinaturas e assinatura_eventos (staging).
Saída: intervalos (assinatura_id, conta_id, estado, plano_id, inicio, fim), eventos corrigidos
       e flags.
Dependências: pandas.

Regras (todas testadas em tests/test_state_machine.py):
- Evento até 24 h antes de `assinatura_criada`: desvio de relógio entre sistemas (o perfil mostra
  minutos). CORRIGE para o instante da criação.
- Cancelamento/encerramento mais de 24 h antes da criação: impossível. CORRIGE pela data do
  cabeçalho da assinatura (cancelamento_solicitado_em / encerrada_em); sem ela, QUARENTENA.
- Transição fora da tabela TRANSITIONS (ex.: qualquer evento depois de `encerrada`): o evento é
  ignorado e SINALIZADO; o estado não muda.
"""

from __future__ import annotations

import pandas as pd

from dq.clean import flags

END_OF_DATA = pd.Timestamp("2026-11-01")
NEUTRAL = {"upgrade", "downgrade", "metodo_pagamento_alterado", "membro_extra_adicionado", "membro_extra_removido"}

# (estado atual, evento) -> próximo estado. Tudo que não está aqui é transição inválida.
TRANSITIONS: dict[tuple[str | None, str], str] = {
    (None, "assinatura_criada"): "ativo",
    ("ativo", "trial_iniciado"): "trial",
    ("ativo", "reativada"): "ativo",
    ("ativo", "inadimplencia_iniciada"): "inadimplente",
    ("ativo", "cancelamento_solicitado"): "cancelamento_agendado",
    ("ativo", "encerrada"): "cancelado",
    ("trial", "trial_convertido"): "ativo",
    ("trial", "inadimplencia_iniciada"): "inadimplente",
    ("trial", "cancelamento_solicitado"): "cancelamento_agendado",
    ("trial", "encerrada"): "cancelado",
    ("inadimplente", "inadimplencia_resolvida"): "ativo",
    ("inadimplente", "inadimplencia_iniciada"): "inadimplente",
    ("inadimplente", "cancelamento_solicitado"): "cancelamento_agendado",
    ("inadimplente", "encerrada"): "cancelado",
    ("cancelamento_agendado", "encerrada"): "cancelado",
    ("cancelamento_agendado", "inadimplencia_iniciada"): "cancelamento_agendado",
    ("cancelamento_agendado", "inadimplencia_resolvida"): "cancelamento_agendado",
}
for _s in ("ativo", "trial", "inadimplente", "cancelamento_agendado"):
    for _e in NEUTRAL:
        TRANSITIONS[(_s, _e)] = _s

# desempate para eventos no mesmo segundo
PRIORITY = {"assinatura_criada": 0, "reativada": 1, "trial_iniciado": 2, "trial_convertido": 3,
            "cancelamento_solicitado": 8, "encerrada": 9}


def step(state: str | None, event: str) -> str | None:
    """Próximo estado, ou None se a transição for inválida."""
    return TRANSITIONS.get((state, event))


def fix_event_order(ev: pd.DataFrame, subs: pd.DataFrame, tol_h: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    ev = ev.copy()
    created = ev[ev["tipo"] == "assinatura_criada"].groupby("assinatura_id")["ocorrido_em"].min()
    created = created.combine_first(subs.set_index("assinatura_id")["iniciada_em"])
    c = ev["assinatura_id"].map(created)
    early = (ev["ocorrido_em"] < c) & (ev["tipo"] != "assinatura_criada")
    skew = early & ((c - ev["ocorrido_em"]) <= pd.Timedelta(hours=tol_h))
    ev.loc[skew, "ocorrido_em"] = c[skew]
    bad = early & ~skew
    hdr = subs.set_index("assinatura_id")
    from_hdr = pd.Series(pd.NaT, index=ev.index, dtype="datetime64[ms]")
    for tipo, col in (("cancelamento_solicitado", "cancelamento_solicitado_em"), ("encerrada", "encerrada_em")):
        m = bad & (ev["tipo"] == tipo)
        from_hdr[m] = ev.loc[m, "assinatura_id"].map(hdr[col]).to_numpy()
    fixable = bad & from_hdr.notna() & (from_hdr >= c)
    ev.loc[fixable, "ocorrido_em"] = from_hdr[fixable]
    drop = bad & ~fixable
    fl = flags.concat([
        flags.make("evento_desvio_relogio", "tolerancia_24h", "assinatura_eventos", ev.loc[skew, "evento_id"], "corrigir"),
        flags.make("evento_fora_de_ordem", "maquina_de_estados+cabecalho", "assinatura_eventos", ev.loc[fixable, "evento_id"], "corrigir"),
        flags.make("evento_fora_de_ordem", "maquina_de_estados", "assinatura_eventos", ev.loc[drop, "evento_id"], "quarentena"),
    ])
    return ev[~drop], fl


def build_timeline(ev: pd.DataFrame, subs: pd.DataFrame, strict: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Intervalos de estado por assinatura. strict=False reproduz o pipeline ingênuo: aplica cada
    evento como veio, sem validar a transição (para medir o custo de não ter a máquina)."""
    hdr = subs.set_index("assinatura_id")
    ev = ev.assign(_p=ev["tipo"].map(PRIORITY).fillna(5)).sort_values(["assinatura_id", "ocorrido_em", "_p", "evento_id"])
    naive_state = {"assinatura_criada": "ativo", "trial_iniciado": "trial", "trial_convertido": "ativo", "reativada": "ativo",
                   "inadimplencia_iniciada": "inadimplente", "inadimplencia_resolvida": "ativo",
                   "cancelamento_solicitado": "cancelamento_agendado", "encerrada": "cancelado"}
    rows, invalid = [], []
    for sid, g in ev.groupby("assinatura_id", sort=False):
        h = hdr.loc[sid]
        plan_ev = g[g["tipo"].isin(["upgrade", "downgrade"])]
        plano = int(plan_ev["plano_anterior_id"].iloc[0]) if len(plan_ev) and pd.notna(plan_ev["plano_anterior_id"].iloc[0]) else int(h["plano_id"])
        state, since = None, None
        for e in g.itertuples():
            nxt = step(state, e.tipo) if strict else naive_state.get(e.tipo, state or "ativo")
            if nxt is None:
                invalid.append(e.evento_id)
                continue
            new_plan = int(e.plano_novo_id) if e.tipo in ("upgrade", "downgrade") and pd.notna(e.plano_novo_id) else plano
            if state is None:
                state, plano, since = nxt, new_plan, e.ocorrido_em
            elif nxt != state or new_plan != plano:
                if e.ocorrido_em > since:
                    rows.append((sid, h["conta_id"], state, plano, since, e.ocorrido_em))
                state, plano, since = nxt, new_plan, max(since, e.ocorrido_em)
        if state is not None and state != "cancelado":
            rows.append((sid, h["conta_id"], state, plano, since, END_OF_DATA))
    tl = pd.DataFrame(rows, columns=["assinatura_id", "conta_id", "estado", "plano_id", "inicio", "fim"])
    tl = tl.merge(subs[["assinatura_id", "periodicidade", "assinatura_anterior_id"]], on="assinatura_id", how="left")
    fl = flags.make("transicao_invalida", "maquina_de_estados", "assinatura_eventos", invalid, "sinalizar")
    return tl, fl


def resolve_overlaps(tl: pd.DataFrame, vigentes: list[str]) -> tuple[pd.Series, pd.DataFrame]:
    """Duas assinaturas vigentes da mesma conta no mesmo dia. Se a mais nova não é reativação
    (sem assinatura_anterior_id) e começa dentro de uma vigente, é duplicata: vai para quarentena
    com faturas e pagamentos, e o financeiro é avisado (pode ter havido cobrança em dobro)."""
    v = tl[tl["estado"].isin(vigentes)]
    span = v.groupby(["assinatura_id", "conta_id"]).agg(inicio=("inicio", "min"), fim=("fim", "max"),
                                                         anterior=("assinatura_anterior_id", "first")).reset_index()
    span = span.sort_values(["conta_id", "inicio"])
    prev_fim = span.groupby("conta_id")["fim"].cummax().groupby(span["conta_id"]).shift()
    dup = (span["inicio"] < prev_fim - pd.Timedelta(days=1)) & span["anterior"].isna()
    ids = span.loc[dup, "assinatura_id"]
    return ids, flags.make("assinatura_sobreposta", "intervalos_por_conta", "assinaturas", ids, "quarentena")
