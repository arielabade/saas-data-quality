"""Utilitários do injetor: contexto de tabelas, alocação de ids, geração de uso e formato raw.

Papel: dar ao injetor um jeito único de (1) criar linhas novas com ids válidos, (2) gerar
       sessões e reproduções coerentes com a base e (3) gravar a camada raw no formato em que
       os dados chegam de verdade (timestamps em texto, com formato por plataforma, e a hora
       de recebimento no servidor).
Entrada: tabelas do snapshot de referência (data/source).
Saída: tabelas em memória; `to_raw` produz o formato da camada raw.
Dependências: pandas, numpy, dq.domain.
"""

from __future__ import annotations

import contextlib

import numpy as np
import pandas as pd

from dq.domain import MOBILE, TZ_OFFSET_H, UF_REGION, UF_TZ, normalize_device_type, normalize_uf

USAGE = ("sessoes_app", "reproducoes")
PKS = {
    "contas": "conta_id", "perfis": "perfil_id", "dispositivos": "dispositivo_id",
    "assinaturas": "assinatura_id", "assinatura_eventos": "evento_id", "faturas": "fatura_id",
    "pagamentos": "pagamento_id", "sessoes_app": "sessao_id", "reproducoes": "reproducao_id",
}


class Ctx:
    """Tabelas em memória + gerador aleatório + alocador de ids."""

    def __init__(self, tables: dict[str, pd.DataFrame], seed: int) -> None:
        self.t = tables
        self.rng = np.random.default_rng(seed)
        self._next = {t: int(tables[t][pk].max()) + 1 for t, pk in PKS.items()}
        self.refresh()

    def refresh(self) -> None:
        dv = self.t["dispositivos"]
        self.dev_type = pd.Series(normalize_device_type(dv["tipo"]).to_numpy(), index=dv["dispositivo_id"])
        self.dev_conta = dv.set_index("dispositivo_id")["conta_id"]
        c = self.t["contas"]
        uf = normalize_uf(c["uf"])
        self.conta_tz = pd.Series(uf.map(UF_TZ).fillna("America/Sao_Paulo").to_numpy(), index=c["conta_id"])
        self.conta_region = pd.Series(uf.map(UF_REGION).to_numpy(), index=c["conta_id"])
        self.perfil_conta = self.t["perfis"].set_index("perfil_id")["conta_id"]

    def ids(self, table: str, n: int) -> np.ndarray:
        start = self._next[table]
        self._next[table] = start + n
        return np.arange(start, start + n, dtype="int64")

    def append(self, table: str, df: pd.DataFrame) -> None:
        cur = self.t[table]
        df = df.reindex(columns=cur.columns)
        for c in cur.columns:  # mantém os tipos da tabela original
            if str(cur[c].dtype) != str(df[c].dtype):
                with contextlib.suppress(TypeError, ValueError):
                    df[c] = df[c].astype(cur[c].dtype)
        self.t[table] = pd.concat([cur, df], ignore_index=True)


def add_received_at(t: dict[str, pd.DataFrame], rng: np.random.Generator) -> None:
    """Hora de recebimento no servidor (UTC). A base fonte não tem essa coluna para sessões e
    reproduções; a camada raw de uma landing zone real tem, e a carga incremental depende dela."""
    for name in USAGE:
        df = t[name]
        end = df[["inicio_em", "fim_em"]].max(axis=1).fillna(df["inicio_em"])
        lat = np.minimum(np.exp(rng.normal(1.0, 1.2, len(df))), 3600).astype("int64")
        df["recebido_em"] = (end + pd.to_timedelta(lat, unit="s")).astype("datetime64[ms]")


def encode_seconds(seconds: np.ndarray, versao: pd.Series, dev_type: pd.Series) -> np.ndarray:
    """Reproduz a peculiaridade nativa do app 6.x móvel, que grava milissegundos (ver DATA_SOURCE)."""
    ms = versao.astype(str).str.startswith("6.").to_numpy() & dev_type.isin(list(MOBILE)).to_numpy()
    return np.where(ms, np.asarray(seconds, dtype="int64") * 1000, np.asarray(seconds, dtype="int64"))


def device_profile(ctx: Ctx) -> pd.DataFrame:
    """Para cada dispositivo: versão de app mais usada e região/IP típicos (para linhas sintéticas)."""
    s = ctx.t["sessoes_app"]
    g = s.groupby("dispositivo_id")
    return pd.DataFrame({
        "versao_app": g["versao_app"].agg(lambda x: x.mode().iat[0]),
        "regiao": g["regiao"].agg(lambda x: x.mode().iat[0] if x.notna().any() else None),
        "ip": g["ip"].first(),
    })


def build_usage(ctx: Ctx, rows: list[dict], versao: dict[int, str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Transforma uma lista de blocos de uso em sessões + reproduções com ids novos.

    Cada bloco: perfil_id, dispositivo_id, inicio (Timestamp UTC), regiao, ip e `itens`
    (lista de (titulo_id, episodio_id|None, duracao_seg, fracao_assistida, gap_seg)).
    Um bloco vira uma sessão; os itens tocam em sequência dentro dela.
    """
    if not rows:
        return pd.DataFrame(), pd.DataFrame()
    sids = ctx.ids("sessoes_app", len(rows))
    sess, plays = [], []
    for sid, b in zip(sids, rows):
        t = b["inicio"] + pd.Timedelta(seconds=int(ctx.rng.integers(5, 60)))
        ver = (versao or {}).get(b["dispositivo_id"], b.get("versao_app", "5.3.0"))
        for k, (tit, ep, dur, frac, gap) in enumerate(b["itens"]):
            watched = max(int(dur * frac), 1)
            start = t + pd.Timedelta(seconds=int(gap))
            end = start + pd.Timedelta(seconds=watched + int(ctx.rng.integers(0, 40)))
            plays.append(dict(perfil_id=b["perfil_id"], sessao_id=sid, dispositivo_id=b["dispositivo_id"],
                              titulo_id=tit, episodio_id=ep, inicio_em=start, fim_em=end, segundos_assistidos=watched,
                              percentual_concluido=round(min(100.0, frac * 100), 2), qualidade_video="1080p",
                              eventos_buffering=0, origem_autoplay=int(k > 0 and ep is not None), origem_recomendacao=0,
                              versao_app=ver))
            t = end
        sess.append(dict(sessao_id=sid, perfil_id=b["perfil_id"], dispositivo_id=b["dispositivo_id"], versao_app=ver,
                         inicio_em=b["inicio"], fim_em=t + pd.Timedelta(seconds=int(ctx.rng.integers(5, 200))),
                         ip=b.get("ip") or "10.0.0.1", regiao=b.get("regiao")))
    s = pd.DataFrame(sess)
    p = pd.DataFrame(plays)
    p.insert(0, "reproducao_id", ctx.ids("reproducoes", len(p)))
    p["episodio_id"] = pd.array(p["episodio_id"], dtype="Int64")
    p["sessao_id"] = pd.array(p["sessao_id"], dtype="Int64")
    dt = p["dispositivo_id"].map(ctx.dev_type)
    p["segundos_assistidos"] = encode_seconds(p["segundos_assistidos"].to_numpy(), p["versao_app"], dt)
    for df in (s, p):
        for c in ("inicio_em", "fim_em"):
            df[c] = pd.to_datetime(df[c]).astype("datetime64[ms]")
        lat = np.minimum(np.exp(ctx.rng.normal(1.0, 1.2, len(df))), 3600).astype("int64")
        df["recebido_em"] = (df["fim_em"] + pd.to_timedelta(lat, unit="s")).astype("datetime64[ms]")
    return s, p


def series_episodes(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ep = t["episodios"].sort_values(["titulo_id", "temporada", "numero"]).copy()
    ep["dur_seg"] = ep["duracao_min"].astype(int) * 60
    return ep


# ---------------------------------------------------------------------------------- formato raw
def _fmt(ts: pd.Series, how: np.ndarray, offset_h: np.ndarray) -> pd.Series:
    """Formata timestamps UTC como cada cliente envia:
    - 'z'      celular/tablet: ISO em UTC com sufixo Z
    - 'offset' web: hora local com offset explícito (-03:00)
    - 'naive'  TV: 'AAAA-MM-DD HH:MM:SS' sem fuso (em UTC, segundo a documentação da fonte)
    - 'local'  defeito: hora local SEM offset (indistinguível de UTC pelo formato de TV)
    """
    out = pd.Series(pd.NA, index=ts.index, dtype="object")
    ok = ts.notna().to_numpy()
    local = ts + pd.to_timedelta(offset_h, unit="h")
    for kind in ("z", "offset", "naive", "local"):
        m = ok & (how == kind)
        if not m.any():
            continue
        if kind == "z":
            out[m] = ts[m].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif kind == "naive":
            out[m] = ts[m].dt.strftime("%Y-%m-%d %H:%M:%S")
        elif kind == "local":
            out[m] = local[m].dt.strftime("%Y-%m-%dT%H:%M:%S")
        else:
            off = pd.Series(offset_h[m], index=ts.index[m]).astype(int)
            sign = np.where(off < 0, "-", "+")
            suffix = pd.Series(sign, index=off.index) + off.abs().map("{:02d}:00".format)
            out[m] = local[m].dt.strftime("%Y-%m-%dT%H:%M:%S") + suffix
    return out


def to_raw(ctx: Ctx) -> dict[str, pd.DataFrame]:
    """Converte as tabelas em memória no formato raw (texto nos timestamps de uso)."""
    out = {k: v.copy() for k, v in ctx.t.items()}
    ctx.refresh()
    for name in USAGE:
        df = out[name]
        dt = df["dispositivo_id"].map(ctx.dev_type).fillna("tv")
        conta = df["perfil_id"].map(ctx.perfil_conta)
        tz = conta.map(ctx.conta_tz).fillna("America/Sao_Paulo")
        off = tz.map(TZ_OFFSET_H).to_numpy()
        how = np.select([dt.isin(list(MOBILE)).to_numpy(), (dt == "web").to_numpy()], ["z", "offset"], "naive")
        if "_fuso_local" in df:
            how = np.where(df["_fuso_local"].fillna(False).to_numpy(), "local", how)
            df = df.drop(columns="_fuso_local")
        for c in ("inicio_em", "fim_em"):
            df[c] = _fmt(df[c], how, off)
        out[name] = df.sort_values("recebido_em", kind="stable").reset_index(drop=True)
    return out
