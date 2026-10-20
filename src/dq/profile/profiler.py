"""Perfil de dados de uma camada (por padrão, o snapshot de referência em data/source).

Papel: descrever cada tabela antes de qualquer regra de limpeza: tipos, nulos, cardinalidade,
       distribuições, unicidade de chaves, integridade entre tabelas e a sequência de eventos
       de cada assinatura. É daqui que saem as regras: nada é limpo sem antes ser medido.
Entrada: pasta com um Parquet por tabela (data/source ou outra camada).
Saída: reports/profile/profile.json (máquina) e reports/profile/PROFILE.md (leitura).
Dependências: pandas, numpy.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from dq.config import settings
from dq.io import read_table

PKS = {
    "canais": ["canal_id"], "planos": ["plano_id"], "precos": ["preco_id"], "contas": ["conta_id"],
    "perfis": ["perfil_id"], "dispositivos": ["dispositivo_id"], "assinaturas": ["assinatura_id"],
    "assinatura_eventos": ["evento_id"], "faturas": ["fatura_id"], "pagamentos": ["pagamento_id"],
    "titulos": ["titulo_id"], "episodios": ["episodio_id"], "sessoes_app": ["sessao_id"],
    "reproducoes": ["reproducao_id"],
}
# (tabela, coluna) -> (tabela referenciada, coluna). Inclui as chaves lógicas dos logs.
FKS = [
    ("precos", "plano_id", "planos", "plano_id"),
    ("contas", "canal_aquisicao_id", "canais", "canal_id"),
    ("contas", "indicada_por_conta_id", "contas", "conta_id"),
    ("perfis", "conta_id", "contas", "conta_id"),
    ("dispositivos", "conta_id", "contas", "conta_id"),
    ("assinaturas", "conta_id", "contas", "conta_id"),
    ("assinaturas", "plano_id", "planos", "plano_id"),
    ("assinaturas", "assinatura_anterior_id", "assinaturas", "assinatura_id"),
    ("assinatura_eventos", "assinatura_id", "assinaturas", "assinatura_id"),
    ("faturas", "assinatura_id", "assinaturas", "assinatura_id"),
    ("faturas", "preco_id", "precos", "preco_id"),
    ("pagamentos", "fatura_id", "faturas", "fatura_id"),
    ("pagamentos", "conta_id", "contas", "conta_id"),
    ("episodios", "titulo_id", "titulos", "titulo_id"),
    ("sessoes_app", "perfil_id", "perfis", "perfil_id"),
    ("sessoes_app", "dispositivo_id", "dispositivos", "dispositivo_id"),
    ("reproducoes", "perfil_id", "perfis", "perfil_id"),
    ("reproducoes", "sessao_id", "sessoes_app", "sessao_id"),
    ("reproducoes", "dispositivo_id", "dispositivos", "dispositivo_id"),
    ("reproducoes", "titulo_id", "titulos", "titulo_id"),
    ("reproducoes", "episodio_id", "episodios", "episodio_id"),
]
CATEGORICAL_MAX = 30  # até esse nº de valores distintos, listamos a distribuição inteira


def profile_column(s: pd.Series) -> dict:
    n = len(s)
    out = {"dtype": str(s.dtype), "nulos": int(s.isna().sum()), "pct_nulos": round(100 * s.isna().mean(), 3) if n else 0}
    nn = s.dropna()
    out["distintos"] = int(nn.nunique())
    if pd.api.types.is_bool_dtype(s) or (pd.api.types.is_numeric_dtype(s) and out["distintos"] <= 2):
        out["tipo"] = "flag"
        out["valores"] = {str(k): int(v) for k, v in nn.value_counts().items()}
    elif pd.api.types.is_numeric_dtype(s):
        out["tipo"] = "numerico"
        if len(nn):
            q = nn.quantile([0, .01, .25, .5, .75, .99, 1]).tolist()
            out.update(min=q[0], p01=q[1], p25=q[2], mediana=q[3], p75=q[4], p99=q[5], max=q[6],
                       media=float(nn.mean()), negativos=int((nn < 0).sum()), zeros=int((nn == 0).sum()))
    elif pd.api.types.is_datetime64_any_dtype(s) or (len(nn) and isinstance(nn.iloc[0], pd.Timestamp | np.datetime64)):
        out["tipo"] = "data_hora"
        if len(nn):
            out.update(min=str(nn.min()), max=str(nn.max()))
            out["antes_2023_10"] = int((nn < pd.Timestamp("2023-10-01")).sum())
            out["depois_2026_10"] = int((nn > pd.Timestamp("2026-11-01")).sum())
    elif len(nn) and hasattr(nn.iloc[0], "isoformat"):
        out["tipo"] = "data"
        out.update(min=str(nn.min()), max=str(nn.max()))
    else:
        out["tipo"] = "texto"
        vc = nn.astype(str).value_counts()
        if out["distintos"] <= CATEGORICAL_MAX:
            out["valores"] = {k: int(v) for k, v in vc.items()}
        else:
            out["top5"] = {k: int(v) for k, v in vc.head(5).items()}
            out["comprimento_mediano"] = float(nn.astype(str).str.len().median())
    return out


def profile_table(name: str, df: pd.DataFrame) -> dict:
    pk = PKS.get(name, [])
    dup_pk = int(df.duplicated(pk).sum()) if pk else None
    return {"linhas": len(df), "colunas": {c: profile_column(df[c]) for c in df.columns},
            "pk": pk, "pk_duplicadas": dup_pk}


def referential(tables: dict[str, pd.DataFrame]) -> list[dict]:
    out = []
    for t, c, rt, rc in FKS:
        if t not in tables or rt not in tables:
            continue
        v = tables[t][c].dropna()
        orf = ~v.isin(tables[rt][rc])
        out.append({"de": f"{t}.{c}", "para": f"{rt}.{rc}", "preenchidos": int(len(v)), "orfaos": int(orf.sum()),
                    "nulos": int(tables[t][c].isna().sum())})
    return out


def subscription_sequences(ass: pd.DataFrame, ev: pd.DataFrame) -> dict:
    """Como churn, reativação e mudança de plano aparecem: transições entre eventos por assinatura."""
    ev = ev.sort_values(["assinatura_id", "ocorrido_em", "evento_id"])
    nxt = ev.groupby("assinatura_id")["tipo"].shift(-1)
    trans = (ev["tipo"] + " -> " + nxt.fillna("FIM")).value_counts()
    first = ev.groupby("assinatura_id")["tipo"].first().value_counts()
    paths = ev.groupby("assinatura_id")["tipo"].agg(lambda x: " > ".join(x)).value_counts().head(12)
    reat = ass["assinatura_anterior_id"].notna()
    # intervalo entre fim da anterior e início da reativação
    prev = ass.set_index("assinatura_id")["encerrada_em"]
    gap = (ass.loc[reat, "iniciada_em"].values - prev.reindex(ass.loc[reat, "assinatura_anterior_id"].astype(int)).values)
    gap_d = pd.Series(gap).dt.total_seconds() / 86400
    por_conta = ass.groupby("conta_id").size()
    # sobreposição nativa: duas assinaturas da mesma conta ativas no mesmo instante
    a = ass.sort_values(["conta_id", "iniciada_em"])
    fim = a["encerrada_em"].fillna(pd.Timestamp("2100-01-01"))
    prev_fim = fim.groupby(a["conta_id"]).shift()
    overlap = int((a["iniciada_em"] < prev_fim).sum())
    # evento fora de ordem nativo: qualquer evento antes de assinatura_criada
    criada = ev[ev["tipo"] == "assinatura_criada"].set_index("assinatura_id")["ocorrido_em"]
    antes = int((ev["ocorrido_em"] < ev["assinatura_id"].map(criada)).sum())
    return {
        "transicoes": {k: int(v) for k, v in trans.head(40).items()},
        "primeiro_evento": {k: int(v) for k, v in first.items()},
        "caminhos_mais_comuns": {k: int(v) for k, v in paths.items()},
        "status_foto_final": {k: int(v) for k, v in ass["status"].value_counts().items()},
        "tipo_encerramento": {str(k): int(v) for k, v in ass["tipo_encerramento"].value_counts(dropna=False).items()},
        "reativacoes": int(reat.sum()),
        "dias_ate_reativar": {"mediana": float(gap_d.median()), "p10": float(gap_d.quantile(.1)),
                              "p90": float(gap_d.quantile(.9)), "min": float(gap_d.min())} if reat.any() else {},
        "assinaturas_por_conta": {str(k): int(v) for k, v in por_conta.value_counts().sort_index().items()},
        "sobreposicoes_nativas": overlap,
        "eventos_antes_da_criacao_nativos": antes,
    }


def native_quirks(t: dict[str, pd.DataFrame]) -> dict:
    """Imperfeições que a base de referência já traz. Elas viram regras de padronização (staging)."""
    r, ep, ti, dv = t["reproducoes"], t["episodios"], t["titulos"], t["dispositivos"]
    dur = r["episodio_id"].map(ep.set_index("episodio_id")["duracao_min"]).fillna(
        r["titulo_id"].map(ti.set_index("titulo_id")["duracao_min"])) * 60
    mob = r["dispositivo_id"].map(dv.set_index("dispositivo_id")["tipo"].str.strip().str.lower())
    v6 = r["versao_app"].str.startswith("6.")
    big = r["segundos_assistidos"] > dur * 5
    pag, fat = t["pagamentos"], t["faturas"]
    paid_ids = set(pag.loc[(pag["status"] == "aprovado") & (pag["tipo"] == "cobranca"), "fatura_id"].dropna())
    contas = t["contas"]
    return {
        "repro_segundos_negativos": int((r["segundos_assistidos"] < 0).sum()),
        "repro_segundos_zero": int((r["segundos_assistidos"] == 0).sum()),
        "repro_maior_que_conteudo": int((r["segundos_assistidos"] > dur * 1.05).sum()),
        "repro_fim_nulo": int(r["fim_em"].isna().sum()),
        "repro_qualidade_nula": int(r["qualidade_video"].isna().sum()),
        "repro_ordem_1000x_app6_movel": int((big & v6 & mob.isin(["celular", "tablet", "smartphone", "mobile"])).sum()),
        "repro_ordem_1000x_fora_app6_movel": int((big & ~(v6 & mob.isin(["celular", "tablet", "smartphone", "mobile"]))).sum()),
        "dispositivo_tipo_variantes": {k: int(v) for k, v in dv["tipo"].value_counts().items()},
        "uf_fora_do_padrao": int((~contas["uf"].str.fullmatch(r"[A-Z]{2}")).sum()),
        "contas_email_interno": int(contas["email"].str.endswith("@cinelume.example").sum()),
        "contas_email_qa": int(contas["email"].str.startswith("qa+").sum()),
        "faturas_pagas_sem_pagamento": int(((fat["status"] == "paga") & ~fat["fatura_id"].isin(paid_ids)).sum()),
        "pagamentos_sem_fatura": int(pag["fatura_id"].isna().sum()),
        "sessoes_regiao_nula": int(t["sessoes_app"]["regiao"].isna().sum()),
        "sessoes_ip_interno": int(t["sessoes_app"]["ip"].str.startswith(("10.", "203.0.113.")).sum()),
    }


def usage_shape(t: dict[str, pd.DataFrame]) -> dict:
    """Distribuição do uso por perfil-dia, a unidade usada pelos detectores de outlier."""
    r = t["reproducoes"]
    s = r["segundos_assistidos"].clip(lower=0, upper=6 * 3600)
    day = r["inicio_em"].dt.floor("D")
    pdia = s.groupby([r["perfil_id"], day]).sum() / 3600
    daily = s.groupby(day).sum() / 3600
    dow = daily.groupby(daily.index.dayofweek).mean()
    return {
        "horas_por_perfil_dia": {k: float(v) for k, v in pdia.describe(percentiles=[.5, .9, .99, .999]).items()},
        "assimetria_horas_perfil_dia": float(pdia.skew()),
        "horas_totais_por_dia_semana": {int(k): float(v) for k, v in dow.items()},
        "top_dias_plataforma": {str(k.date()): float(v) for k, v in daily.sort_values().tail(8).items()},
    }


def run(folder: Path | None = None, out: Path | None = None) -> dict:
    cfg = settings()
    folder = folder or cfg["paths"]["source"]
    out = out or cfg["paths"]["profile_out"]
    names = [n for n in cfg["extract"]["tables"] if (folder / f"{n}.parquet").exists()]
    tables = {n: read_table(folder, n) for n in names}
    prof = {
        "tabelas": {n: profile_table(n, df) for n, df in tables.items()},
        "integridade": referential(tables),
        "sequencias_assinatura": subscription_sequences(tables["assinaturas"], tables["assinatura_eventos"]),
        "imperfeicoes_nativas": native_quirks(tables),
        "uso": usage_shape(tables),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "profile.json").write_text(json.dumps(prof, indent=2, ensure_ascii=False, default=str))
    (out / "PROFILE.md").write_text(to_markdown(prof))
    print(f"[profile] {len(tables)} tabelas perfiladas -> {out}")
    return prof


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,d}"
    return str(v)


def to_markdown(p: dict) -> str:
    L = ["# Perfil de dados (gerado)", "",
         "Gerado por `python -m dq.profile.profiler`. Não edite à mão: a leitura está em docs/DATA_SOURCE.md.", ""]
    L += ["## Tabelas", "", "| Tabela | Linhas | PK | PK duplicadas |", "|---|---:|---|---:|"]
    for n, t in p["tabelas"].items():
        L.append(f"| `{n}` | {t['linhas']:,d} | {', '.join(t['pk'])} | {t['pk_duplicadas']} |")
    for n, t in p["tabelas"].items():
        L += ["", f"### `{n}`", "", "| Coluna | Tipo | Nulos % | Distintos | Resumo |", "|---|---|---:|---:|---|"]
        for c, s in t["colunas"].items():
            if s.get("tipo") == "numerico":
                res = f"min {_fmt(s.get('min'))} · p50 {_fmt(s.get('mediana'))} · p99 {_fmt(s.get('p99'))} · max {_fmt(s.get('max'))}"
                if s.get("negativos"):
                    res += f" · **{s['negativos']:,d} negativos**"
            elif s.get("tipo") in ("data_hora", "data"):
                res = f"{s.get('min')} → {s.get('max')}"
            elif "valores" in s:
                res = ", ".join(f"{k}: {v:,d}" for k, v in list(s["valores"].items())[:8])
            else:
                res = "top: " + ", ".join(f"{k[:24]} ({v})" for k, v in list(s.get("top5", {}).items())[:3])
            L.append(f"| {c} | {s.get('tipo', s['dtype'])} | {s['pct_nulos']:.2f} | {s['distintos']:,d} | {res} |")
    L += ["", "## Integridade referencial", "", "| De | Para | Preenchidos | Órfãos | Nulos |", "|---|---|---:|---:|---:|"]
    for r in p["integridade"]:
        L.append(f"| {r['de']} | {r['para']} | {r['preenchidos']:,d} | {r['orfaos']:,d} | {r['nulos']:,d} |")
    sq = p["sequencias_assinatura"]
    L += ["", "## Sequência de eventos por assinatura", "", "| Transição | Ocorrências |", "|---|---:|"]
    L += [f"| {k} | {v:,d} |" for k, v in sq["transicoes"].items()]
    L += ["", "| Caminho completo | Assinaturas |", "|---|---:|"]
    L += [f"| {k} | {v:,d} |" for k, v in sq["caminhos_mais_comuns"].items()]
    L += ["", "## Imperfeições nativas da base de referência", "", "| Achado | Valor |", "|---|---:|"]
    L += [f"| {k} | {_fmt(v)} |" for k, v in p["imperfeicoes_nativas"].items() if not isinstance(v, dict)]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    run(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
