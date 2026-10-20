"""Avaliação completa (make evaluate).

Papel: rodar as variantes do ETL, medir cada técnica contra o registro de defeitos, comparar as
       métricas de negócio com a verdade, medir o viés num modelo de churn, demonstrar a carga
       incremental com atrasados e comparar escalas de uso.
Entrada: data/raw, data/raw_reference, data/defect_log, data/runs/limpo (de make etl).
Saída: reports/resultados/*.json|csv e reports/RESULTADOS.md.
Dependências: dq.evaluate.*, dq.pipeline, dq.clean.scaling.
"""

from __future__ import annotations

import json
import shutil

import numpy as np
import pandas as pd

from dq.clean import scaling
from dq.config import settings
from dq.evaluate import business, churn_model, detection
from dq.evaluate.variants import ABLATIONS, run_all, run_dir, variant_specs
from dq.io import read_table

ABLATION_LABELS = {
    "ingenua": "Nenhuma limpeza (só padronizar formato)",
    "sem_contas_internas": "Não filtrar contas internas e de teste",
    "sem_bots": "Não excluir robôs",
    "sem_quarentena_orfaos": "Não pôr órfãos em quarentena",
    "sem_dedup_pagamentos": "Não deduplicar webhook de pagamento",
    "sem_dedup_uso": "Não deduplicar replay de lote",
    "sem_fuso_e_relogio": "Não corrigir fuso e relógio",
    "sem_unificar_dispositivos": "Não unificar IDs de aparelho",
    "sem_limites_fisicos": "Não aplicar limites físicos",
    "sem_maquina_estados": "Usar eventos de assinatura como vieram",
    "sem_sobreposicao_assinaturas": "Não resolver assinaturas sobrepostas",
    "sem_preco_scd": "Não conferir preço com o SCD",
    "outlier_como_erro": "Remover outliers de IQR como se fossem erro",
    "janela_0": "Descartar eventos atrasados (janela 0)",
}


def _out():
    d = settings()["paths"]["reports"] / "resultados"
    d.mkdir(parents=True, exist_ok=True)
    return d


def incremental_demo() -> dict:
    """Corte 1 -> corte 2 (uma semana depois) -> corte 2 de novo: o que é recalculado em cada passo."""
    from dq.pipeline import run_etl

    cfg = settings()
    d = cfg["paths"]["runs"] / "incremental_demo"
    shutil.rmtree(d, ignore_errors=True)
    steps = []
    for label, cut in (("carga até 31/08/2026", "2026-08-31 23:59:59"), ("+1 semana de lotes", "2026-09-07 23:59:59"),
                       ("mesma semana de novo", "2026-09-07 23:59:59")):
        rep = run_etl(cfg["paths"]["raw"], d, cutoff=cut, verbose=False)
        steps.append({"passo": label, "corte": cut, "meses_particao_alterados": rep["meses_particoes_alteradas"],
                      "meses_engajamento_recalculados": rep["meses_engajamento_recalculados"]})
    return {"passos": steps}


def late_window(log: pd.DataFrame) -> pd.DataFrame:
    """Quantos atrasados entram no mês certo com janela 30 vs janela 0."""
    late = set(log.loc[(log["tipo"] == "atrasado") & (log["tabela"] == "reproducoes"), "chave"])
    rows = []
    for v in ("limpa", "janela_0"):
        q = read_table(run_dir(v), "quarentena")
        lost = set(q.loc[(q["tabela"] == "reproducoes") & (q["motivo"] == "atrasado_fora_da_janela"), "chave"])
        rows.append({"variante": v, "atrasados": len(late), "em_quarentena": len(late & lost),
                     "incorporados_pct": 100 * (1 - len(late & lost) / len(late)) if late else np.nan})
    return pd.DataFrame(rows)


def scales() -> tuple[pd.DataFrame, dict]:
    from dq.load.incremental import Warehouse

    r = Warehouse(run_dir("limpa") / "warehouse").read("reproducoes")
    h = (r.groupby(["perfil_id", "dia_local"])["segundos_assistidos"].sum() / 3600)
    sample = h.sample(min(len(h), 60000), random_state=1)
    sc = scaling.all_scales(sample)
    hist = {c: np.histogram(sc[c], bins=40) for c in sc.columns}
    return scaling.shape_summary(sc), {c: {"contagem": v[0].tolist(), "bordas": v[1].round(4).tolist()} for c, v in hist.items()}


def daily_story(log: pd.DataFrame) -> dict:
    """Série diária de horas (suja e verdade), o esperado pelo modelo sazonal e os dias marcados."""
    from dq.clean import outliers, timestamps
    from dq.config import load_yaml

    oc = load_yaml("cleaning")["outliers"]
    out = {}
    for name in ("limpa", "verdade"):
        st = {n: read_table(run_dir(name) / "staging", n) for n in ("contas", "reproducoes", "episodios")}
        r = st["reproducoes"].dropna(subset=["conta_id"])
        tz = timestamps.account_tz(st["contas"])
        daily = outliers.daily_series(outliers.perfil_day(r, tz))
        out[name] = daily
        if name == "limpa":
            seas = outliers.seasonal_flags(daily, oc["sazonal_janela_dias"], oc["sazonal_z"])
            expl = outliers.explain_days(seas, r.assign(inicio_em=outliers.local_time(r["inicio_em"], r["conta_id"], tz)), st["episodios"])
            naive = outliers.naive_daily_flags(daily, oc["sazonal_z"])
    lr = log[log["tabela"] == "reproducoes"]
    ev = {}
    for tipo in ("replay_lote", "maratona_lancamento", "pico_feriado"):
        d = lr.loc[lr["tipo"] == tipo, "data"].dt.strftime("%Y-%m-%d").value_counts()
        ev[tipo] = sorted(d[d > 50].index)
    return {"datas": [x.strftime("%Y-%m-%d") for x in out["limpa"].index], "suja": out["limpa"].round(1).tolist(),
            "verdade": out["verdade"].reindex(out["limpa"].index).round(1).tolist(),
            "esperado": seas["esperado"].round(1).tolist(),
            "marcados": [{"data": d.strftime("%Y-%m-%d"), "explicacao": e, "z": round(float(z), 1)}
                         for d, e, z in zip(expl.index, expl["explicacao"], expl["z"])],
            "z_simples": [d.strftime("%Y-%m-%d") for d in daily.index[naive.to_numpy()]], "eventos": ev}


def wrong_decisions(err: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for v, label in ABLATION_LABELS.items():
        e = err[err["variante"] == v].set_index("metrica")
        if e.empty:
            continue
        base = err[err["variante"] == "limpa"].set_index("metrica")["erro_medio"]
        effect = (e["erro_medio"] - base).loc[["mrr", "ativos", "churn", "horas"]]
        top = effect.abs().idxmax()   # a métrica que a decisão mais move em relação ao pipeline completo
        rows.append({"variante": v, "decisao": label, "metrica_mais_afetada": e.loc[top, "rotulo"],
                     "erro_medio": e.loc[top, "erro_medio"], "efeito_vs_limpa": float(effect[top]), "unidade": e.loc[top, "unidade"],
                     "pior_mes": e.loc[top, "pior_mes"], "erro_pior_mes": e.loc[top, "erro_pior_mes"],
                     **{f"erro_{k}": e.loc[k, "erro_medio"] for k in ("mrr", "ativos", "churn", "horas")}})
    return pd.DataFrame(rows)


def evaluate(rerun: bool = True) -> dict:
    cfg = settings()
    out = _out()
    specs = variant_specs()
    todo = [n for n in specs if rerun or not (run_dir(n) / "marts" / "mrr.parquet").exists()]
    if todo:
        run_all(todo)
    log = detection.load_defect_log()

    det, imput = detection.evaluate_all()
    det.to_csv(out / "deteccao.csv", index=False)

    variants = ["verdade", "ingenua", "limpa", "outlier_como_erro", "janela_0"] + [f"sem_{a}" for a in ABLATIONS]
    long = business.long_series(variants)
    long.to_csv(out / "series.csv", index=False)
    err = business.errors(long)
    err.to_csv(out / "erros.csv", index=False)
    coh = business.cohort_summary(["verdade", "ingenua", "limpa"])
    raw_counts = {t: len(read_table(cfg["paths"]["raw"], t)) for t in cfg["extract"]["tables"]}
    dirty = business.dirty_share(log, raw_counts)
    dirty.to_csv(out / "base_suja.csv", index=False)
    wrong = wrong_decisions(err)
    wrong.to_csv(out / "decisoes_erradas.csv", index=False)

    cm = churn_model.analyze()
    for k, v in cm.items():
        v.to_csv(out / f"churn_modelo_{k}.csv", index=False)
    shape, hist = scales()
    shape.to_csv(out / "escalas.csv", index=False)
    lw = late_window(log)
    story = daily_story(log)
    inc = incremental_demo()

    reps = {v: json.loads((run_dir(v) / "qualidade.json").read_text()) for v in ("verdade", "limpa")}
    summary = {
        "deteccao": det.to_dict("records"), "imputacao": imput, "erros": err.to_dict("records"),
        "coortes": coh.to_dict("records"), "base_suja": dirty.to_dict("records"), "decisoes_erradas": wrong.to_dict("records"),
        "churn_modelo": {k: v.to_dict("records") for k, v in cm.items()}, "escalas": shape.to_dict("records"),
        "escalas_hist": hist, "atrasados": lw.to_dict("records"), "incremental": inc, "serie_diaria": story,
        "registro": log.groupby(["categoria", "tipo"]).size().rename("linhas").reset_index().to_dict("records"),
        "nulos": reps["limpa"]["nulos"],
        "qualidade_limpa": {k: reps["limpa"][k] for k in ("quarentena", "flags", "contratos", "padronizacao")},
        "nativos_referencia": {k: reps["verdade"][k] for k in ("flags", "quarentena")},
    }
    (out / "resultados.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str))
    from dq.report.results_md import write_results_md
    write_results_md(summary, cfg["paths"]["reports"] / "RESULTADOS.md")
    print(f"[evaluate] resultados em {out}")
    return summary


if __name__ == "__main__":
    evaluate()
