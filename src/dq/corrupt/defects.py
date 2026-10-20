"""Defeitos típicos de um SaaS de streaming, injetados com registro.

Papel: alterar a cópia da base de forma realista e anotar cada alteração no DefectLog.
Entrada: Ctx com a base de referência (já com outliers legítimos) e config/corruption.yaml.
Saída: tabelas sujas em memória; uma entrada de registro por linha/entidade afetada.
Dependências: dq.corrupt.base, dq.corrupt.log, dq.domain.

Ordem: primeiro as alterações em linhas existentes, depois as inserções (duplicatas, clones,
órfãos). Assim cada linha inserida carrega um único tipo de defeito no registro.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dq.corrupt.base import Ctx, build_usage, encode_seconds
from dq.corrupt.log import DefectLog
from dq.domain import MOBILE, QA_NETWORK, content_seconds

DAY = pd.Timedelta(days=1)


def _sample(ctx: Ctx, idx: pd.Index, rate: float | None = None, n: int | None = None) -> pd.Index:
    n = int(round(len(idx) * rate)) if n is None else min(n, len(idx))
    return pd.Index(ctx.rng.choice(idx.to_numpy(), size=n, replace=False)) if n else pd.Index([])


def _conta_of_perfil(ctx: Ctx, perfil: pd.Series) -> pd.Series:
    return perfil.map(ctx.perfil_conta)


def _log_rows(log: DefectLog, ctx: Ctx, tipo: str, table: str, df: pd.DataFrame, coluna: str, orig, sujo) -> None:
    key = "reproducao_id" if table == "reproducoes" else "sessao_id"
    log.add("defeito", tipo, table, df[key], coluna, orig, sujo, conta_id=_conta_of_perfil(ctx, df["perfil_id"]),
            perfil_id=df["perfil_id"], dispositivo_id=df["dispositivo_id"], data=df["inicio_em"])


# ------------------------------------------------------------------------------- uso: valores
def watch_time_defects(ctx: Ctx, log: DefectLog, cfg: dict, original_ids: set[int]) -> None:
    r = ctx.t["reproducoes"]
    dt = r["dispositivo_id"].map(ctx.dev_type)
    dur = content_seconds(r, ctx.t["episodios"], ctx.t["titulos"])
    elig = r.index[r["reproducao_id"].isin(original_ids) & dur.notna() & (r["segundos_assistidos"] > 0)]

    neg = _sample(ctx, elig, cfg["tempo_negativo"]["taxa"])
    v = -ctx.rng.integers(60, 3600, len(neg))
    new = encode_seconds(v, r.loc[neg, "versao_app"], dt.loc[neg])
    _log_rows(log, ctx, "tempo_negativo", "reproducoes", r.loc[neg], "segundos_assistidos", r.loc[neg, "segundos_assistidos"], new)
    r.loc[neg, "segundos_assistidos"] = new

    rest = elig.difference(neg)
    c = cfg["tempo_maior_que_conteudo"]
    big = _sample(ctx, rest, c["taxa"])
    v = (dur.loc[big] * ctx.rng.uniform(c["fator_min"], c["fator_max"], len(big))).astype("int64").to_numpy()
    new = encode_seconds(v, r.loc[big, "versao_app"], dt.loc[big])
    _log_rows(log, ctx, "tempo_maior_que_conteudo", "reproducoes", r.loc[big], "segundos_assistidos", r.loc[big, "segundos_assistidos"], new)
    r.loc[big, "segundos_assistidos"] = new

    rest = rest.difference(big)
    c = cfg["sessao_absurda"]
    ab = _sample(ctx, rest, c["taxa"])
    secs = (ctx.rng.uniform(c["horas_min"], c["horas_max"], len(ab)) * 3600).astype("int64")
    new = encode_seconds(secs, r.loc[ab, "versao_app"], dt.loc[ab])
    _log_rows(log, ctx, "sessao_absurda", "reproducoes", r.loc[ab], "segundos_assistidos", r.loc[ab, "segundos_assistidos"], new)
    r.loc[ab, "segundos_assistidos"] = new
    r.loc[ab, "fim_em"] = (r.loc[ab, "inicio_em"] + pd.to_timedelta(secs, unit="s")).to_numpy()
    r.loc[ab, "recebido_em"] = (r.loc[ab, "fim_em"] + pd.Timedelta(seconds=30)).to_numpy()
    # a sessão acompanha o player aberto
    s = ctx.t["sessoes_app"]
    fim = r.loc[ab].groupby("sessao_id")["fim_em"].max()
    m = s["sessao_id"].isin(fim.index)
    s.loc[m, "fim_em"] = np.maximum(s.loc[m, "fim_em"].to_numpy(), s.loc[m, "sessao_id"].map(fim).to_numpy())
    s.loc[m, "recebido_em"] = (s.loc[m, "fim_em"] + pd.Timedelta(seconds=30)).to_numpy()


# ------------------------------------------------------------------------------- uso: tempo
def clock_and_timezone(ctx: Ctx, log: DefectLog, cfg: dict) -> None:
    """Fuso misturado (web grava hora local sem offset) e aparelhos com relógio errado."""
    c = cfg["fuso_misturado"]
    for name in ("sessoes_app", "reproducoes"):
        df = ctx.t[name]
        m = (df["dispositivo_id"].map(ctx.dev_type) == c["plataforma"]) & df["inicio_em"].between(c["inicio"], c["fim"])
        df["_fuso_local"] = m
        _log_rows(log, ctx, "fuso_misturado", name, df[m], "inicio_em", "UTC com offset", "local sem offset")

    s = ctx.t["sessoes_app"]
    counts = s.groupby("dispositivo_id").size()
    devs = _sample(ctx, pd.Index(counts[counts >= 20].index), cfg["relogio_errado"]["taxa_dispositivos"])
    kind = ctx.rng.choice(4, len(devs), p=[.35, .3, .2, .15])
    sign = ctx.rng.choice([-1, 1], len(devs))
    off = np.select([kind == 0, kind == 1, kind == 2],
                    [sign * 3600, sign * ctx.rng.integers(2, 13, len(devs)) * 3600,
                     sign * ctx.rng.integers(1, 41, len(devs)) * 86400], -1)
    offs = pd.Series(off, index=devs)
    t0 = pd.Timestamp("2023-10-01")
    for name in ("sessoes_app", "reproducoes"):
        df = ctx.t[name]
        m = df["dispositivo_id"].isin(devs)
        o = df.loc[m, "dispositivo_id"].map(offs)
        _log_rows(log, ctx, "relogio_errado", name, df[m], "inicio_em", df.loc[m, "inicio_em"], o)
        for col in ("inicio_em", "fim_em"):
            t = df.loc[m, col]
            shifted = t + pd.to_timedelta(o.where(o != -1, 0), unit="s")
            reset = pd.Timestamp("2000-01-01") + (t - t0) % pd.Timedelta(days=40)
            df.loc[m, col] = shifted.where(o != -1, reset).to_numpy()


def late_arrivals(ctx: Ctx, log: DefectLog, cfg: dict) -> None:
    """Sincronização offline do celular: a sessão inteira (e suas reproduções) chega dias depois."""
    c = cfg["atrasados"]
    s = ctx.t["sessoes_app"]
    mob = s.index[s["dispositivo_id"].map(ctx.dev_type).isin(list(MOBILE)) & (s["inicio_em"] > "2023-10-03")]
    pick = _sample(ctx, mob, c["taxa_movel"])
    delay = pd.to_timedelta(ctx.rng.uniform(c["dias_min"], c["dias_max"], len(pick)) * 86400, unit="s").round("s")
    d = pd.Series(delay, index=s.loc[pick, "sessao_id"].to_numpy())
    _log_rows(log, ctx, "atrasado", "sessoes_app", s.loc[pick], "recebido_em", s.loc[pick, "recebido_em"], s.loc[pick, "recebido_em"] + delay)
    s.loc[pick, "recebido_em"] = (s.loc[pick, "recebido_em"] + delay).to_numpy()
    r = ctx.t["reproducoes"]
    m = r["sessao_id"].isin(d.index)
    dd = r.loc[m, "sessao_id"].map(d)
    _log_rows(log, ctx, "atrasado", "reproducoes", r[m], "recebido_em", r.loc[m, "recebido_em"], r.loc[m, "recebido_em"] + dd)
    r.loc[m, "recebido_em"] = (r.loc[m, "recebido_em"] + dd).to_numpy()


def device_swaps(ctx: Ctx, log: DefectLog, cfg: dict) -> None:
    """Reinstalação do app gera dispositivo_id novo para o mesmo aparelho a partir de uma data."""
    s = ctx.t["sessoes_app"]
    span = s.groupby("dispositivo_id")["inicio_em"].agg(["min", "max", "size"])
    span = span[(span["max"] - span["min"] > pd.Timedelta(days=90)) & (span["size"] >= 30)]
    devs = _sample(ctx, span.index, cfg["troca_dispositivo"]["taxa_dispositivos"])
    dv = ctx.t["dispositivos"].set_index("dispositivo_id")
    new_ids = ctx.ids("dispositivos", len(devs))
    cut = {}
    rows = []
    for old, new in zip(devs, new_ids):
        a, b = span.loc[old, "min"], span.loc[old, "max"]
        when = a + (b - a) * ctx.rng.uniform(0.3, 0.7)
        cut[old] = (new, when)
        src = dv.loc[old]
        rows.append(dict(dispositivo_id=new, conta_id=src["conta_id"], tipo=src["tipo"], plataforma=src["plataforma"],
                         registrado_em=pd.Timestamp(when).floor("s")))
    ctx.append("dispositivos", pd.DataFrame(rows))
    ctx.refresh()
    for name in ("sessoes_app", "reproducoes"):
        df = ctx.t[name]
        m = df["dispositivo_id"].isin(devs)
        when = df.loc[m, "dispositivo_id"].map({k: v[1] for k, v in cut.items()})
        after = df.loc[m].index[(df.loc[m, "inicio_em"] >= when).to_numpy()]
        df.loc[after, "dispositivo_id"] = df.loc[after, "dispositivo_id"].map({k: v[0] for k, v in cut.items()}).to_numpy()
    log.add("defeito", "troca_dispositivo", "dispositivos", new_ids, "dispositivo_id", list(devs), list(new_ids),
            conta_id=[dv.loc[o, "conta_id"] for o in devs], dispositivo_id=new_ids, data=[cut[o][1] for o in devs])


def batch_replay(ctx: Ctx, log: DefectLog, cfg: dict, original_ids: set[int]) -> None:
    """Reprocessamento de lote: horas inteiras de sessões e reproduções duplicadas com ids novos."""
    c = cfg["replay_lote"]
    s, r = ctx.t["sessoes_app"], ctx.t["reproducoes"]
    days = pd.date_range("2024-02-01", "2026-09-30", freq="D")
    days = days[~days.strftime("%m-%d").isin(["12-24", "12-25", "12-31", "01-01"])]
    chosen = ctx.rng.choice(days, c["dias"], replace=False)
    for day in pd.to_datetime(chosen):
        h0 = 0 if c["horas_por_dia"] >= 24 else int(ctx.rng.integers(0, 24 - c["horas_por_dia"]))
        lo, hi = day + pd.Timedelta(hours=h0), day + pd.Timedelta(hours=h0 + c["horas_por_dia"])
        ss = s[s["inicio_em"].between(lo, hi) & s["sessao_id"].isin(r.loc[r["reproducao_id"].isin(original_ids), "sessao_id"])].copy()
        rr = r[r["sessao_id"].isin(ss["sessao_id"])].copy()
        new_sid = pd.Series(ctx.ids("sessoes_app", len(ss)), index=ss["sessao_id"].to_numpy())
        ss["sessao_id"] = ss["sessao_id"].map(new_sid).to_numpy()
        rr["sessao_id"] = pd.array(rr["sessao_id"].map(new_sid), dtype="Int64")
        rr["reproducao_id"] = ctx.ids("reproducoes", len(rr))
        late = pd.Timedelta(hours=int(ctx.rng.integers(20, 40)))
        ss["recebido_em"] = ss["recebido_em"] + late
        rr["recebido_em"] = rr["recebido_em"] + late
        ctx.append("sessoes_app", ss)
        ctx.append("reproducoes", rr)
        _log_rows(log, ctx, "replay_lote", "sessoes_app", ss, "linha_inserida", None, "duplicata")
        _log_rows(log, ctx, "replay_lote", "reproducoes", rr, "linha_inserida", None, "duplicata")


# ------------------------------------------------------------------------------- cobrança
def subscription_events_out_of_order(ctx: Ctx, log: DefectLog, cfg: dict) -> None:
    ev, a = ctx.t["assinatura_eventos"], ctx.t["assinaturas"]
    start = a.set_index("assinatura_id")["iniciada_em"]
    cand = ev.index[ev["tipo"].isin(["cancelamento_solicitado", "encerrada"])]
    subs = ev.loc[cand, "assinatura_id"].unique()
    chosen = set(ctx.rng.choice(subs, int(len(subs) * cfg["eventos_fora_de_ordem"]["taxa_assinaturas"]), replace=False))
    idx = ev.loc[cand][ev.loc[cand, "assinatura_id"].isin(chosen)].drop_duplicates("assinatura_id").index
    new = ev.loc[idx, "assinatura_id"].map(start) - pd.to_timedelta(ctx.rng.integers(2, 120, len(idx)), unit="D")
    log.add("defeito", "evento_fora_de_ordem", "assinatura_eventos", ev.loc[idx, "evento_id"], "ocorrido_em",
            ev.loc[idx, "ocorrido_em"], new, conta_id=ev.loc[idx, "assinatura_id"].map(a.set_index("assinatura_id")["conta_id"]),
            data=ev.loc[idx, "ocorrido_em"])
    ev.loc[idx, "ocorrido_em"] = new.dt.floor("s").to_numpy()


def stale_prices(ctx: Ctx, log: DefectLog, cfg: dict) -> None:
    """Fatura emitida com o preço da tabela anterior (cache de preço vencido)."""
    f, pr, pg = ctx.t["faturas"], ctx.t["precos"], ctx.t["pagamentos"]
    pr = pr[pr["item"] == "assinatura"].copy()
    pr["vigencia_inicio"] = pd.to_datetime(pr["vigencia_inicio"])
    cur = pr.set_index("preco_id")
    prev = {}
    for (_plano, _per), g in pr.sort_values("vigencia_inicio").groupby(["plano_id", "periodicidade"]):
        ids = g["preco_id"].tolist()
        prev.update({b: a for a, b in zip(ids[:-1], ids[1:])})
    elig = f.index[f["preco_id"].isin(list(prev)) & (f["valor_bruto"] > 0)]
    idx = _sample(ctx, elig, cfg["preco_divergente"]["taxa"])
    old = f.loc[idx, "preco_id"].map(prev)
    new_bruto = old.map(cur["valor_brl"])
    new_total = (new_bruto - f.loc[idx, "valor_desconto"] + f.loc[idx, "valor_membro_extra"]).round(2).clip(lower=0)
    conta = f.loc[idx, "conta_id"]
    log.add("defeito", "preco_divergente", "faturas", f.loc[idx, "fatura_id"], "valor_bruto", f.loc[idx, "valor_bruto"],
            new_bruto, conta_id=conta, data=f.loc[idx, "periodo_inicio"])
    f.loc[idx, "preco_id"] = old.to_numpy()
    f.loc[idx, "valor_bruto"] = new_bruto.to_numpy()
    f.loc[idx, "valor_total"] = new_total.to_numpy()
    # o pagamento foi registrado com o valor (errado) da fatura
    tot = pd.Series(new_total.to_numpy(), index=f.loc[idx, "fatura_id"].to_numpy())
    m = pg["fatura_id"].isin(tot.index) & (pg["tipo"] == "cobranca")
    pv = pg.loc[m, "fatura_id"].astype("int64").map(tot)
    log.add("defeito", "preco_divergente", "pagamentos", pg.loc[m, "pagamento_id"], "valor_brl", pg.loc[m, "valor_brl"], pv,
            conta_id=pg.loc[m, "conta_id"], data=pg.loc[m, "processado_em"])
    pg.loc[m, "valor_brl"] = pv.to_numpy()


def duplicate_payments(ctx: Ctx, log: DefectLog, cfg: dict) -> None:
    pg = ctx.t["pagamentos"]
    approved = pg.index[(pg["status"] == "aprovado") & (pg["tipo"] == "cobranca")]
    declined = pg.index[pg["status"] == "recusado"]
    for tipo, elig, c in (
        ("webhook_duplicado", approved, cfg["webhook_duplicado"]),
        ("retentativa_duplicada", declined, cfg["retentativa_duplicada"]),
    ):
        idx = _sample(ctx, elig, c["taxa"])
        dup = pg.loc[idx].copy()
        dup["pagamento_id"] = ctx.ids("pagamentos", len(dup))
        dup["processado_em"] = dup["processado_em"] + pd.to_timedelta(ctx.rng.integers(1, c["atraso_max_seg"], len(dup)), unit="s")
        ctx.append("pagamentos", dup)
        pg = ctx.t["pagamentos"]
        log.add("defeito", tipo, "pagamentos", dup["pagamento_id"], "linha_inserida", None, "duplicata",
                conta_id=dup["conta_id"], data=dup["processado_em"])


def overlapping_subscriptions(ctx: Ctx, log: DefectLog, cfg: dict) -> None:
    """Upgrade gravado como assinatura nova, sem encerrar a anterior: dois planos ativos no mesmo dia."""
    a, pr = ctx.t["assinaturas"], ctx.t["precos"]
    active = a[a["encerrada_em"].isna() & (a["iniciada_em"] < "2026-06-01") & (a["status"] == "ativa")]
    pick = active.loc[_sample(ctx, active.index, cfg["assinaturas_sobrepostas"]["taxa_contas"])]
    pr = pr[pr["item"] == "assinatura"].copy()
    pr["vi"] = pd.to_datetime(pr["vigencia_inicio"])
    end = pd.Timestamp("2026-10-31")
    subs, evs, fats, pags = [], [], [], []
    for row in pick.itertuples():
        d0 = pd.Timestamp(row.iniciada_em) + pd.Timedelta(days=30)
        start = (d0 + (end - pd.Timedelta(days=45) - d0) * ctx.rng.uniform(0.1, 0.9)).floor("s")
        plano = int(row.plano_id % 3 + 1)
        sid = int(ctx.ids("assinaturas", 1)[0])
        subs.append(dict(assinatura_id=sid, conta_id=row.conta_id, plano_id=plano, periodicidade=row.periodicidade,
                         metodo_pagamento=row.metodo_pagamento, status="ativa", iniciada_em=start,
                         renovacao_automatica=row.renovacao_automatica))
        evs.append(dict(evento_id=int(ctx.ids("assinatura_eventos", 1)[0]), assinatura_id=sid, tipo="assinatura_criada",
                        ocorrido_em=start, origem="app"))
        step = pd.DateOffset(years=1) if row.periodicidade == "anual" else pd.DateOffset(months=1)
        ini = start.normalize()
        while ini <= end:
            p = pr[(pr["plano_id"] == plano) & (pr["periodicidade"] == row.periodicidade) & (pr["vi"] <= ini)].sort_values("vi").iloc[-1]
            fid = int(ctx.ids("faturas", 1)[0])
            fim = ini + step - pd.Timedelta(days=1)
            fats.append(dict(fatura_id=fid, assinatura_id=sid, conta_id=row.conta_id, preco_id=int(p["preco_id"]),
                             periodo_inicio=ini.date(), periodo_fim=fim.date(), emitida_em=ini + pd.Timedelta(hours=9),
                             vencimento_em=(ini + pd.Timedelta(days=3)).date(), valor_bruto=float(p["valor_brl"]),
                             valor_desconto=0.0, valor_membro_extra=0.0, valor_total=float(p["valor_brl"]), status="paga"))
            pags.append(dict(pagamento_id=int(ctx.ids("pagamentos", 1)[0]), fatura_id=fid, conta_id=row.conta_id,
                             metodo=row.metodo_pagamento, tipo="cobranca", tentativa=1,
                             processado_em=ini + pd.Timedelta(hours=9, minutes=int(ctx.rng.integers(1, 50))),
                             valor_brl=float(p["valor_brl"]), status="aprovado"))
            ini = ini + step
    for name, rows, key, dcol in (("assinaturas", subs, "assinatura_id", "iniciada_em"),
                                  ("assinatura_eventos", evs, "evento_id", "ocorrido_em"),
                                  ("faturas", fats, "fatura_id", "periodo_inicio"),
                                  ("pagamentos", pags, "pagamento_id", "processado_em")):
        df = pd.DataFrame(rows)
        if df.empty:
            continue
        ctx.append(name, df)
        conta = df["conta_id"] if "conta_id" in df else df["assinatura_id"].map(pd.DataFrame(subs).set_index("assinatura_id")["conta_id"])
        log.add("defeito", "assinatura_sobreposta", name, df[key], "linha_inserida", None, "nova", conta_id=conta, data=df[dcol])


# ------------------------------------------------------------------------------- cadastro
def null_uf_tv_signup(ctx: Ctx, log: DefectLog, cfg: dict) -> None:
    """UF nula quando o cadastro foi feito pela TV (o app de TV não pede endereço): nulo MAR."""
    dv = ctx.t["dispositivos"].sort_values(["conta_id", "registrado_em"])
    first = dv.drop_duplicates("conta_id").set_index("conta_id")["tipo"]
    c = ctx.t["contas"]
    tv = c["conta_id"].map(first).map(lambda x: str(x).strip().lower() in ("tv", "smart tv"))
    idx = _sample(ctx, c.index[tv & c["uf"].notna()], cfg["nulo_uf_tv"]["taxa"])
    log.add("defeito", "nulo_uf_tv", "contas", c.loc[idx, "conta_id"], "uf", c.loc[idx, "uf"], None, conta_id=c.loc[idx, "conta_id"])
    c.loc[idx, "uf"] = None


def _clone_accounts(ctx: Ctx, contas: list[int], keep_usage: bool) -> dict[str, pd.DataFrame]:
    """Clona contas com todo o histórico (assinaturas, cobrança, perfis, aparelhos e uso) e ids novos."""
    t = ctx.t
    out: dict[str, pd.DataFrame] = {}
    maps: dict[str, pd.Series] = {}

    def remap(name: str, key: str, rows: pd.DataFrame) -> pd.DataFrame:
        rows = rows.copy()
        maps[key] = pd.Series(ctx.ids(name, len(rows)), index=rows[key].to_numpy())
        rows[key] = rows[key].map(maps[key]).to_numpy()
        return rows

    out["contas"] = remap("contas", "conta_id", t["contas"][t["contas"]["conta_id"].isin(contas)])
    out["contas"]["indicada_por_conta_id"] = pd.array([pd.NA] * len(out["contas"]), dtype="Int64")
    for name, key in (("perfis", "perfil_id"), ("dispositivos", "dispositivo_id"), ("assinaturas", "assinatura_id")):
        rows = remap(name, key, t[name][t[name]["conta_id"].isin(contas)])
        rows["conta_id"] = rows["conta_id"].map(maps["conta_id"]).to_numpy()
        out[name] = rows
    out["assinaturas"]["assinatura_anterior_id"] = pd.array(
        out["assinaturas"]["assinatura_anterior_id"].map(maps["assinatura_id"]), dtype="Int64")
    ev = remap("assinatura_eventos", "evento_id", t["assinatura_eventos"][t["assinatura_eventos"]["assinatura_id"].isin(maps["assinatura_id"].index)])
    ev["assinatura_id"] = ev["assinatura_id"].map(maps["assinatura_id"]).to_numpy()
    out["assinatura_eventos"] = ev
    f = remap("faturas", "fatura_id", t["faturas"][t["faturas"]["assinatura_id"].isin(maps["assinatura_id"].index)])
    f["assinatura_id"] = f["assinatura_id"].map(maps["assinatura_id"]).to_numpy()
    f["conta_id"] = f["conta_id"].map(maps["conta_id"]).to_numpy()
    f["cupom_resgate_id"] = pd.array([pd.NA] * len(f), dtype="Int64")
    out["faturas"] = f
    pg = remap("pagamentos", "pagamento_id", t["pagamentos"][t["pagamentos"]["conta_id"].isin(contas)])
    pg["fatura_id"] = pd.array(pg["fatura_id"].map(maps["fatura_id"]), dtype="Int64")
    pg["conta_id"] = pg["conta_id"].map(maps["conta_id"]).to_numpy()
    out["pagamentos"] = pg
    if keep_usage:
        s = remap("sessoes_app", "sessao_id", t["sessoes_app"][t["sessoes_app"]["perfil_id"].isin(maps["perfil_id"].index)])
        s["perfil_id"] = s["perfil_id"].map(maps["perfil_id"]).to_numpy()
        s["dispositivo_id"] = s["dispositivo_id"].map(maps["dispositivo_id"]).to_numpy()
        r = remap("reproducoes", "reproducao_id", t["reproducoes"][t["reproducoes"]["sessao_id"].isin(maps["sessao_id"].index)])
        r["sessao_id"] = pd.array(r["sessao_id"].map(maps["sessao_id"]), dtype="Int64")
        r["perfil_id"] = r["perfil_id"].map(maps["perfil_id"]).to_numpy()
        r["dispositivo_id"] = r["dispositivo_id"].map(maps["dispositivo_id"]).to_numpy()
        out["sessoes_app"], out["reproducoes"] = s, r
    out["_maps"] = maps  # type: ignore[assignment]
    return out


def _customer_accounts(ctx: Ctx, exclude: set[int]) -> pd.Index:
    c = ctx.t["contas"]
    a = ctx.t["assinaturas"]
    ok = ~c["email"].str.endswith("cinelume.example") & ~c["conta_id"].isin(exclude) & c["conta_id"].isin(a["conta_id"])
    return pd.Index(c.loc[ok, "conta_id"])


def test_accounts(ctx: Ctx, log: DefectLog, cfg: dict, exclude: set[int]) -> set[int]:
    """Contas internas/QA criadas como cópia de clientes, com sinais de teste nem sempre óbvios."""
    n = cfg["contas_teste"]["n"]
    src = list(ctx.rng.choice(_customer_accounts(ctx, exclude), n, replace=False))
    cl = _clone_accounts(ctx, src, keep_usage=True)
    c = cl["contas"]
    k = len(c)
    sig = ctx.rng.random((k, 4)) < [0.5, 0.3, 0.4, 0.5]   # email, nome, cpf inválido, rede de QA
    sig[~sig.any(1), int(ctx.rng.integers(4))] = True
    nums = ctx.rng.integers(100, 999, k)
    user = c["email"].str.split("@").str[0]
    dom = c["email"].str.split("@").str[1]
    pat = ctx.rng.integers(0, 3, k)
    new_email = np.where(pat == 0, "qa.automacao+" + pd.Series(nums).astype(str).to_numpy() + "@" + dom.to_numpy(),
                         np.where(pat == 1, "teste." + user.to_numpy() + "@" + dom.to_numpy(),
                                  user.to_numpy() + ".homolog@" + dom.to_numpy()))
    # sem sinal de e-mail, o clone ainda precisa de e-mail único (sufixo numérico, como um cliente real)
    plain = user.to_numpy() + pd.Series(nums).astype(str).to_numpy() + "@" + dom.to_numpy()
    c["email"] = np.where(sig[:, 0], new_email, plain)
    c["nome_titular"] = np.where(sig[:, 1], "Usuário Teste " + pd.Series(nums).astype(str).to_numpy(), c["nome_titular"])
    bad_cpf = [f"{a:03d}.{b:03d}.{d:03d}-00" for a, b, d in ctx.rng.integers(100, 999, (k, 3))]
    c["cpf"] = np.where(sig[:, 2], bad_cpf, c["cpf"])   # sem esse sinal o CPF fica duplicado do cliente original
    qa_conta = set(c.loc[sig[:, 3], "conta_id"])
    s = cl["sessoes_app"]
    qa_perfis = set(cl["perfis"].loc[cl["perfis"]["conta_id"].isin(qa_conta), "perfil_id"])
    m = s["perfil_id"].isin(qa_perfis)
    s.loc[m, "ip"] = [f"{QA_NETWORK}{a}.{b}" for a, b in ctx.rng.integers(1, 255, (int(m.sum()), 2))]
    for name in ("contas", "perfis", "dispositivos", "assinaturas", "assinatura_eventos", "faturas", "pagamentos",
                 "sessoes_app", "reproducoes"):
        ctx.append(name, cl[name])
    ctx.refresh()
    ids = c["conta_id"].tolist()
    log.add("defeito", "conta_teste", "contas", ids, "conta_id", src, ids, conta_id=ids)
    return set(ids)


def bot_accounts(ctx: Ctx, log: DefectLog, cfg: dict, exclude: set[int]) -> None:
    """Contas usadas por robô: dezenas de reproduções curtas por dia, a qualquer hora, sempre no web."""
    c = cfg["bots"]
    src = list(ctx.rng.choice(_customer_accounts(ctx, exclude), c["n_contas"], replace=False))
    cl = _clone_accounts(ctx, src, keep_usage=False)
    cl["contas"]["email"] = cl["contas"]["email"].str.replace("@", f"{ctx.rng.integers(10, 99)}@", n=1, regex=False)
    for name in ("contas", "perfis", "dispositivos", "assinaturas", "assinatura_eventos", "faturas", "pagamentos"):
        ctx.append(name, cl[name])
    ctx.refresh()
    films = ctx.t["titulos"].loc[ctx.t["titulos"]["tipo"] == "filme", ["titulo_id", "duracao_min"]].to_numpy()
    blocks = []
    for conta in cl["contas"]["conta_id"]:
        sub = cl["assinaturas"][cl["assinaturas"]["conta_id"] == conta].iloc[0]
        perfil = int(cl["perfis"].loc[cl["perfis"]["conta_id"] == conta, "perfil_id"].iloc[0])
        did = int(ctx.ids("dispositivos", 1)[0])
        ctx.append("dispositivos", pd.DataFrame([dict(dispositivo_id=did, conta_id=conta, tipo="web", plataforma="web",
                                                      registrado_em=pd.Timestamp(sub["iniciada_em"]).floor("s"))]))
        ctx.refresh()
        day0 = pd.Timestamp(sub["iniciada_em"]).normalize() + pd.Timedelta(days=int(ctx.rng.integers(1, 30)))
        for d in range(int(ctx.rng.integers(30, 90))):
            day = day0 + pd.Timedelta(days=d)
            for h in range(24):
                k = int(ctx.rng.poisson(c["reproducoes_por_dia"] / 24))
                if not k:
                    continue
                items = [(int(f[0]), None, int(f[1]) * 60, float(ctx.rng.uniform(30, 120)) / (int(f[1]) * 60), 3)
                         for f in films[ctx.rng.integers(0, len(films), k)]]
                blocks.append(dict(perfil_id=perfil, dispositivo_id=did, inicio=day + pd.Timedelta(hours=h, minutes=int(ctx.rng.integers(0, 50))),
                                   regiao=None, ip=f"198.51.100.{int(ctx.rng.integers(1, 255))}", versao_app="5.3.0", itens=items))
    s, p = build_usage(ctx, blocks)
    ctx.append("sessoes_app", s)
    ctx.append("reproducoes", p)
    ids = cl["contas"]["conta_id"].tolist()
    log.add("defeito", "bot", "contas", ids, "conta_id", src, ids, conta_id=ids)
    _log_rows(log, ctx, "bot", "reproducoes", p, "linha_inserida", None, "nova")


def orphans(ctx: Ctx, log: DefectLog, cfg: dict) -> None:
    """Pagamento sem fatura/assinatura conhecida e sessão de perfil inexistente."""
    c = cfg["orfaos"]
    pg = ctx.t["pagamentos"]
    idx = _sample(ctx, pg.index[pg["fatura_id"].notna()], c["pagamentos"])
    o = pg.loc[idx].copy()
    o["pagamento_id"] = ctx.ids("pagamentos", len(o))
    o["fatura_id"] = pd.array(ctx.ids("faturas", len(o)) + 10_000_000, dtype="Int64")  # nunca emitida
    ctx.append("pagamentos", o)
    log.add("defeito", "orfao", "pagamentos", o["pagamento_id"], "fatura_id", None, o["fatura_id"], conta_id=o["conta_id"],
            data=o["processado_em"])
    s, r = ctx.t["sessoes_app"], ctx.t["reproducoes"]
    idx = _sample(ctx, s.index, c["sessoes"])
    ss = s.loc[idx].copy()
    ghost = ctx.ids("perfis", len(ss)) + 10_000_000  # perfil apagado / nunca sincronizado
    sid = pd.Series(ctx.ids("sessoes_app", len(ss)), index=ss["sessao_id"].to_numpy())
    pmap = pd.Series(ghost, index=ss["sessao_id"].to_numpy())
    rr = r[r["sessao_id"].isin(sid.index)].copy()
    rr["perfil_id"] = rr["sessao_id"].map(pmap).to_numpy()
    rr["sessao_id"] = pd.array(rr["sessao_id"].map(sid), dtype="Int64")
    rr["reproducao_id"] = ctx.ids("reproducoes", len(rr))
    ss["perfil_id"] = ghost
    ss["sessao_id"] = sid.to_numpy()
    ctx.append("sessoes_app", ss)
    ctx.append("reproducoes", rr)
    for name, df, key in (("sessoes_app", ss, "sessao_id"), ("reproducoes", rr, "reproducao_id")):
        log.add("defeito", "orfao", name, df[key], "perfil_id", None, df["perfil_id"], perfil_id=df["perfil_id"],
                dispositivo_id=df["dispositivo_id"], data=df["inicio_em"])


def apply_defects(ctx: Ctx, log: DefectLog, cfg: dict) -> None:
    d = cfg["defeitos"]
    original_plays = set(ctx.t["reproducoes"]["reproducao_id"])
    used = set(log.frame()["conta_id"].dropna().astype(int)) if len(log.frame()) else set()
    # 1) alterações em linhas existentes
    watch_time_defects(ctx, log, d, original_plays)
    subscription_events_out_of_order(ctx, log, d)
    stale_prices(ctx, log, d)
    null_uf_tv_signup(ctx, log, d)
    late_arrivals(ctx, log, d)
    clock_and_timezone(ctx, log, d)
    device_swaps(ctx, log, d)
    # 2) inserções
    batch_replay(ctx, log, d, original_plays)
    duplicate_payments(ctx, log, d)
    overlapping_subscriptions(ctx, log, d)
    test_ids = test_accounts(ctx, log, d, used)
    bot_accounts(ctx, log, d, used | test_ids)
    orphans(ctx, log, d)
    if "_fuso_local" in ctx.t["sessoes_app"]:
        for name in ("sessoes_app", "reproducoes"):
            ctx.t[name]["_fuso_local"] = ctx.t[name]["_fuso_local"].astype("boolean").fillna(False)
