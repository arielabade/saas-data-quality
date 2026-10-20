"""Outliers verdadeiros e anomalias reais (entram na referência E na base suja).

Papel: colocar na base o que parece erro mas é real, para medir quantos acertos a limpeza
       destrói por engano:
       - legítimo: maratona na estreia de série, usuários muito intensos, pico de feriado e
         compartilhamento de conta pago e dentro do limite de telas;
       - anomalia: compartilhamento acima do limite de telas (uso real que pede ação comercial,
         não exclusão).
Entrada: Ctx com o snapshot de referência; parâmetros `legitimos` e `defeitos.compartilhamento_excedente`.
Saída: linhas novas em sessoes_app, reproducoes, perfis e dispositivos + entradas no registro.
Dependências: dq.corrupt.base, dq.corrupt.log.
"""

from __future__ import annotations

import pandas as pd

from dq.corrupt.base import Ctx, build_usage, device_profile, series_episodes
from dq.corrupt.log import DefectLog
from dq.domain import HOLIDAYS, TZ_OFFSET_H


def _active_perfis(ctx: Ctx, day: pd.Timestamp, plans: tuple[int, ...] = (1, 2, 3)) -> pd.DataFrame:
    """Perfis (com o dispositivo mais usado) de contas com assinatura ativa no dia."""
    a = ctx.t["assinaturas"]
    ok = (a["iniciada_em"] <= day) & (a["encerrada_em"].isna() | (a["encerrada_em"] > day + pd.Timedelta(days=30)))
    contas = a.loc[ok & a["plano_id"].isin(plans), ["conta_id", "plano_id"]].drop_duplicates("conta_id")
    r = ctx.t["reproducoes"]
    win = r[(r["inicio_em"] > day - pd.Timedelta(days=60)) & (r["inicio_em"] < day)]
    top = win.groupby(["perfil_id", "dispositivo_id"]).size().reset_index(name="n")
    top = top.sort_values("n").drop_duplicates("perfil_id", keep="last")
    top["conta_id"] = top["perfil_id"].map(ctx.perfil_conta)
    return top.merge(contas, on="conta_id")


def _evening(ctx: Ctx, day: pd.Timestamp, conta: int, hour: float) -> pd.Timestamp:
    off = TZ_OFFSET_H[ctx.conta_tz.get(conta, "America/Sao_Paulo")]
    return day + pd.Timedelta(hours=hour - off) + pd.Timedelta(minutes=int(ctx.rng.integers(0, 50)))


def _record(log: DefectLog, cat: str, tipo: str, s: pd.DataFrame, p: pd.DataFrame, ctx: Ctx) -> None:
    if p.empty:
        return
    conta = p["perfil_id"].map(ctx.perfil_conta)
    log.add(cat, tipo, "reproducoes", p["reproducao_id"], "linha_inserida", None, "nova",
            conta_id=conta, perfil_id=p["perfil_id"], dispositivo_id=p["dispositivo_id"], data=p["inicio_em"])
    log.add(cat, tipo, "sessoes_app", s["sessao_id"], "linha_inserida", None, "nova",
            conta_id=s["perfil_id"].map(ctx.perfil_conta), perfil_id=s["perfil_id"],
            dispositivo_id=s["dispositivo_id"], data=s["inicio_em"])


def _commit(ctx: Ctx, s: pd.DataFrame, p: pd.DataFrame) -> None:
    if not s.empty:
        ctx.append("sessoes_app", s)
        ctx.append("reproducoes", p)


def release_marathon(ctx: Ctx, log: DefectLog, n_perfis: int, dias: int, devp: pd.DataFrame) -> None:
    """Estreia de temporada original: centenas de perfis assistem 6 a 12 episódios em poucos dias."""
    t = ctx.t
    ep = series_episodes(t)
    orig = set(t["titulos"].loc[(t["titulos"]["original"] == 1) & (t["titulos"]["tipo"] == "serie"), "titulo_id"])
    seasons = ep[ep["titulo_id"].isin(orig)].groupby(["titulo_id", "temporada"]).agg(
        estreia=("disponivel_desde", "min"), n=("episodio_id", "size")).reset_index()
    seasons = seasons[(seasons["n"] >= 8) & (seasons["estreia"] > "2024-06-01") & (seasons["estreia"] < "2026-09-01")]
    picks = seasons.sample(2, random_state=int(ctx.rng.integers(1e9))) if len(seasons) >= 2 else seasons
    blocks = []
    for k, row in enumerate(picks.itertuples()):
        day0 = pd.Timestamp(row.estreia).normalize()
        cand = _active_perfis(ctx, day0)
        chosen = cand.sample(min(len(cand), n_perfis // len(picks)), random_state=int(ctx.rng.integers(1e9)))
        eps = ep[(ep["titulo_id"] == row.titulo_id) & (ep["temporada"] == row.temporada)]
        for c in chosen.itertuples():
            pos = 0
            total = int(ctx.rng.integers(6, min(13, len(eps) + 1)))
            for d in range(dias):
                if pos >= total:
                    break
                n_today = int(min(total - pos, ctx.rng.integers(3, 7)))
                items = [(row.titulo_id, int(e.episodio_id), int(e.dur_seg), float(ctx.rng.uniform(.95, 1.0)),
                          int(ctx.rng.integers(8, 30))) for e in eps.iloc[pos:pos + n_today].itertuples()]
                pos += n_today
                dp = devp.reindex([c.dispositivo_id])
                blocks.append(dict(perfil_id=c.perfil_id, dispositivo_id=c.dispositivo_id,
                                   inicio=_evening(ctx, day0 + pd.Timedelta(days=d), c.conta_id, 19 + k % 2),
                                   regiao=dp["regiao"].iat[0], ip=dp["ip"].iat[0], itens=items))
    s, p = build_usage(ctx, blocks, devp["versao_app"].to_dict())
    _commit(ctx, s, p)
    _record(log, "legitimo", "maratona_lancamento", s, p, ctx)


def intense_users(ctx: Ctx, log: DefectLog, n_perfis: int, dias: int, devp: pd.DataFrame) -> None:
    """Perfis com 8 a 14 h/dia por semanas: extremo, mas fisicamente possível."""
    ep = series_episodes(ctx.t)
    series = ep.groupby("titulo_id").filter(lambda g: len(g) >= 20)["titulo_id"].unique()
    blocks = []
    starts = pd.date_range("2024-03-01", "2026-08-01", freq="D")
    for _ in range(n_perfis):
        day0 = starts[int(ctx.rng.integers(len(starts)))]
        cand = _active_perfis(ctx, day0)
        cand = cand[cand["dispositivo_id"].map(ctx.dev_type) == "tv"]
        if cand.empty:
            continue
        c = cand.sample(1, random_state=int(ctx.rng.integers(1e9))).iloc[0]
        tit = int(series[int(ctx.rng.integers(len(series)))])
        eps = ep[ep["titulo_id"] == tit].reset_index(drop=True)
        pos = 0
        for d in range(dias):
            target = ctx.rng.uniform(8, 14) * 3600
            items, acc = [], 0.0
            while acc < target:
                e = eps.iloc[pos % len(eps)]
                items.append((tit, int(e.episodio_id), int(e.dur_seg), float(ctx.rng.uniform(.9, 1)), int(ctx.rng.integers(8, 40))))
                acc += e.dur_seg
                pos += 1
            dp = devp.reindex([c.dispositivo_id])
            blocks.append(dict(perfil_id=int(c.perfil_id), dispositivo_id=int(c.dispositivo_id),
                               inicio=_evening(ctx, day0 + pd.Timedelta(days=d), int(c.conta_id), 9),
                               regiao=dp["regiao"].iat[0], ip=dp["ip"].iat[0], itens=items))
    s, p = build_usage(ctx, blocks, devp["versao_app"].to_dict())
    _commit(ctx, s, p)
    _record(log, "legitimo", "usuario_intenso", s, p, ctx)


def holiday_peak(ctx: Ctx, log: DefectLog, fator: float) -> None:
    """Natal e Réveillon: parte das pessoas assiste de novo mais tarde no mesmo dia."""
    r, s = ctx.t["reproducoes"], ctx.t["sessoes_app"]
    md = r["inicio_em"].dt.strftime("%m-%d")
    pick = r[md.isin(HOLIDAYS) & (ctx.rng.random(len(r)) < fator)]
    if pick.empty:
        return
    shift = pd.to_timedelta(ctx.rng.integers(3600, 3 * 3600, len(pick)), unit="s")
    sess_src = s.set_index("sessao_id").reindex(pick["sessao_id"].astype("int64"))
    new_sid = ctx.ids("sessoes_app", len(pick))
    ns = pd.DataFrame({"sessao_id": new_sid, "perfil_id": pick["perfil_id"].to_numpy(),
                       "dispositivo_id": pick["dispositivo_id"].to_numpy(), "versao_app": pick["versao_app"].to_numpy(),
                       "inicio_em": (pick["inicio_em"] + shift - pd.Timedelta(seconds=30)).to_numpy(),
                       "fim_em": (pick["fim_em"].fillna(pick["inicio_em"]) + shift + pd.Timedelta(seconds=60)).to_numpy(),
                       "ip": sess_src["ip"].fillna("10.0.0.1").to_numpy(), "regiao": sess_src["regiao"].to_numpy()})
    np_ = pick.copy()
    np_["reproducao_id"] = ctx.ids("reproducoes", len(pick))
    np_["sessao_id"] = pd.array(new_sid, dtype="Int64")
    np_["inicio_em"] = pick["inicio_em"] + shift
    np_["fim_em"] = pick["fim_em"] + shift
    np_["origem_autoplay"] = 0
    for df in (ns, np_):
        df["recebido_em"] = (df["fim_em"].fillna(df["inicio_em"]) + pd.Timedelta(seconds=5)).astype("datetime64[ms]")
        for c in ("inicio_em", "fim_em"):
            df[c] = df[c].astype("datetime64[ms]")
    _commit(ctx, ns, np_)
    _record(log, "legitimo", "pico_feriado", ns, np_, ctx)


def _extra_device(ctx: Ctx, conta: int, when: pd.Timestamp, n: int, extra_profile: bool) -> tuple[list[int], list[int]]:
    """Cria n dispositivos móveis (e, se pedido, um perfil de membro extra) numa conta."""
    dids = ctx.ids("dispositivos", n)
    ctx.append("dispositivos", pd.DataFrame({
        "dispositivo_id": dids, "conta_id": conta, "tipo": "celular", "plataforma": "mobile_os_a",
        "registrado_em": pd.Timestamp(when).floor("s")}))
    perfis = ctx.t["perfis"]
    if extra_profile:
        pid = ctx.ids("perfis", 1)
        ctx.append("perfis", pd.DataFrame({
            "perfil_id": pid, "conta_id": conta, "nome": "Extra", "infantil": 0, "principal": 0, "membro_extra": 1,
            "telemetria_detalhada": 0, "criado_em": pd.Timestamp(when).floor("s"), "excluido_em": pd.NaT}))
        pids = [int(pid[0])] * n
    else:
        own = perfis.loc[perfis["conta_id"] == conta, "perfil_id"].tolist()
        pids = [int(own[i % len(own)]) for i in range(n)]
    ctx.refresh()
    return dids.tolist(), pids


def account_sharing(ctx: Ctx, log: DefectLog, n_contas: int, excess: bool) -> None:
    """Compartilhamento: dentro do limite (legítimo, membro extra pago) ou acima do limite de telas
    (anomalia: telas simultâneas > plano, a partir de outras regiões)."""
    from dq.domain import plan_screens

    screens = plan_screens(ctx.t["planos"])
    a = ctx.t["assinaturas"]
    cand = a[(a["iniciada_em"] < "2026-06-01") & a["encerrada_em"].isna() & a["plano_id"].isin([3] if not excess else [1, 2, 3])]
    used = set(log.frame()["conta_id"].dropna().astype(int)) if len(log.frame()) else set()
    cand = cand[~cand["conta_id"].isin(used)].drop_duplicates("conta_id")
    chosen = cand.sample(min(n_contas, len(cand)), random_state=int(ctx.rng.integers(1e9)))
    titles = ctx.t["titulos"]
    films = titles[titles["tipo"] == "filme"][["titulo_id", "duracao_min"]].to_numpy()
    regions = ["Norte", "Nordeste", "Sul", "Centro-Oeste", "Sudeste"]
    blocks, contas = [], []
    for row in chosen.itertuples():
        start = max(pd.Timestamp(row.iniciada_em), pd.Timestamp("2025-03-10")) + pd.Timedelta(days=int(ctx.rng.integers(5, 60)))
        n_dev = screens[int(row.plano_id)] + 1 if excess else 1
        dids, pids = _extra_device(ctx, int(row.conta_id), start, n_dev, extra_profile=not excess)
        home = ctx.conta_region.get(row.conta_id)
        other = [r for r in regions if r != home]
        dias = int(ctx.rng.integers(35, 60))
        for d in range(dias):
            if not excess and ctx.rng.random() < 0.4:   # membro extra não assiste todo dia
                continue
            day = (start + pd.Timedelta(days=d)).normalize()
            # anomalia: todos os aparelhos extras tocam ao mesmo tempo -> telas > limite do plano
            t0 = _evening(ctx, day, int(row.conta_id), 20 if excess else float(ctx.rng.integers(13, 18)))
            for did, pid in zip(dids, pids):
                f = films[int(ctx.rng.integers(len(films)))]
                blocks.append(dict(perfil_id=pid, dispositivo_id=did, inicio=t0, regiao=other[did % len(other)],
                                   ip=f"177.{did % 200}.{d % 250}.{int(ctx.rng.integers(1, 250))}", versao_app="5.3.0",
                                   itens=[(int(f[0]), None, int(f[1]) * 60, float(ctx.rng.uniform(.8, 1)), 20)]))
        contas.append(int(row.conta_id))
    s, p = build_usage(ctx, blocks)
    _commit(ctx, s, p)
    cat, tipo = ("anomalia", "compartilhamento_excedente") if excess else ("legitimo", "compartilhamento_legitimo")
    log.add(cat, tipo, "contas", contas, "conta_id", conta_id=contas)
    _record(log, cat, tipo, s, p, ctx)


def apply_legit(ctx: Ctx, log: DefectLog, cfg: dict) -> None:
    lg, df = cfg["legitimos"], cfg["defeitos"]
    devp = device_profile(ctx)
    release_marathon(ctx, log, lg["maratona_lancamento"]["n_perfis"], lg["maratona_lancamento"]["dias_apos_estreia"], devp)
    intense_users(ctx, log, lg["usuarios_intensos"]["n_perfis"], lg["usuarios_intensos"]["dias"], devp)
    holiday_peak(ctx, log, lg["pico_feriado"]["fator"])
    account_sharing(ctx, log, lg["compartilhamento_legitimo"]["n_contas"], excess=False)
    account_sharing(ctx, log, df["compartilhamento_excedente"]["n_contas"], excess=True)
    assert not ctx.t["dispositivos"]["dispositivo_id"].map(ctx.dev_type).isna().any()
