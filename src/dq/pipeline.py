"""Orquestração do ETL: raw -> staging -> clean -> marts, e os comandos do Makefile.

Papel: aplicar as regras na ordem certa, com cada uma podendo ser desligada (para medir o custo
       de não aplicá-la), e gravar camadas, marcações, quarentena e relatório de qualidade.
Entrada: uma pasta raw (data/raw ou data/raw_reference) e config/cleaning.yaml.
Saída: data/runs/<variante>/{staging,clean,warehouse,marts}/, flags.parquet, quarentena.parquet,
       qualidade.json e qualidade.md.
Dependências: dq.clean, dq.state, dq.load, dq.contracts.

O ETL não conhece o registro de defeitos: só o evaluate o lê (tests/test_defect_log_guard.py).

Uso: python -m dq.pipeline etl|evaluate|report
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import pandas as pd

from dq.clean import dedup, devices, nulls, outliers, test_accounts, timestamps, usage_limits
from dq.clean import flags as F
from dq.clean.standardize import standardize
from dq.config import load_yaml, settings
from dq.contracts.schemas import validate
from dq.domain import plan_screens
from dq.io import read_layer, write_layer, write_table
from dq.load import marts, quarantine
from dq.load.incremental import Warehouse, assign_batches
from dq.state import churn, machine, scd

ALL_RULES_OFF = {k: False for k in load_yaml("cleaning")["regras"]}


def _h(*parts) -> str:
    m = hashlib.sha1()
    for p in parts:
        m.update(str(p).encode())
    return m.hexdigest()[:16]


def run_etl(raw_dir: Path, run_dir: Path, rules: dict | None = None, cutoff: str | None = None,
            persist_staging: bool = False, strict_contracts: bool | None = None, verbose: bool = True) -> dict:
    t_start = time.time()
    ccfg = load_yaml("cleaning")
    R = {**ccfg["regras"], **(rules or {})}
    strict = all(v for k, v in R.items() if k != "outlier_como_erro") if strict_contracts is None else strict_contracts
    names = settings()["extract"]["tables"]
    raw = read_layer(raw_dir, names)
    if cutoff:
        for n in ("sessoes_app", "reproducoes"):
            raw[n] = raw[n][raw[n]["recebido_em"] <= pd.Timestamp(cutoff)]
    rep: dict = {"variante": run_dir.name, "regras": R, "corte": cutoff,
                 "linhas": {"raw": {k: len(v) for k, v in raw.items()}}}
    contracts = validate("raw", raw, raise_on_fail=False)

    # ------------------------------------------------------------------ staging
    t, rep["padronizacao"] = standardize(raw)
    del raw
    contracts += validate("staging", t, raise_on_fail=False)
    rep["linhas"]["staging"] = {k: len(v) for k, v in t.items()}
    if persist_staging:
        write_layer(t, run_dir / "staging")
    fl: list[pd.DataFrame] = []
    q: list[pd.DataFrame] = []

    # ------------------------------------------------------------------ cadastro e nulos
    excluded: set[int] = set()
    if R["contas_internas"]:
        found = test_accounts.detect(t["contas"], t["sessoes_app"])
        excluded |= set(found["conta_id"])
        fl.append(test_accounts.to_flags(found))
    rep["nulos"] = nulls.mechanism_report(t["contas"], t["dispositivos"], t["assinaturas"]).to_dict("records")
    if R["imputar_regiao"]:
        t["contas"], f = nulls.impute_region(t["contas"], t["sessoes_app"])
        fl.append(f)
    tz = timestamps.account_tz(t["contas"])

    # ------------------------------------------------------------------ integridade
    if R["quarentena_orfaos"]:
        t, qq, f = quarantine.referential(t)
        q.append(qq)
        fl.append(f)

    # ------------------------------------------------------------------ cobrança
    if R["dedup_pagamentos"]:
        t["pagamentos"], f = dedup.dedup_payments(t["pagamentos"], ccfg["dedup"]["pagamentos_chave"],
                                                  ccfg["dedup"]["pagamentos_janela_seg"])
        fl.append(f)
    dim_preco = scd.build_price_scd(t["precos"])
    if R["preco_scd"]:
        t["faturas"], t["pagamentos"], f = scd.check_invoices(t["faturas"], t["pagamentos"], dim_preco)
        fl.append(f)

    # ------------------------------------------------------------------ estado da assinatura
    ev = t["assinatura_eventos"]
    if R["maquina_estados"]:
        ev, f = machine.fix_event_order(ev, t["assinaturas"], ccfg["tempo"]["tolerancia_evento_antes_criacao_h"])
        fl.append(f)
        q.append(quarantine.entries("assinatura_eventos", f.loc[f["acao"] == "quarentena", "chave"], "evento_impossivel"))
    tl, f = machine.build_timeline(ev, t["assinaturas"], strict=R["maquina_estados"])
    fl.append(f)
    if R["sobreposicao_assinaturas"]:
        ids, f = machine.resolve_overlaps(tl, ccfg["churn"]["estados_vigentes"])
        fl.append(f)
        q.append(quarantine.drop_subscriptions(t, ids, "assinatura_sobreposta"))
        tl = tl[~tl["assinatura_id"].isin(set(ids))]
    t["assinatura_eventos"] = ev
    spans = churn.account_spans(tl, ccfg["churn"]["estados_vigentes"],
                                ccfg["churn"]["carencia_reativacao_dias"] if R["maquina_estados"] else 0)

    # ------------------------------------------------------------------ uso
    s, r = t["sessoes_app"], t["reproducoes"]
    if R["fuso_e_relogio"]:
        s, f1 = timestamps.fix_timezone(s, tz, "sessoes_app", "sessao_id")
        r, f2 = timestamps.fix_timezone(r, tz, "reproducoes", "reproducao_id")
        tc = ccfg["tempo"]
        prof = timestamps.clock_profile([s, r], tc["relogio_desvio_min"], tc["relogio_consistencia"], tc["ano_minimo_valido"])
        s, f3 = timestamps.fix_clock(s, prof, "sessoes_app", "sessao_id", tc["ano_minimo_valido"])
        r, f4 = timestamps.fix_clock(r, prof, "reproducoes", "reproducao_id", tc["ano_minimo_valido"])
        fl += [f1, f2, f3, f4]
    fl.append(timestamps.mark_late(s, "sessoes_app", "sessao_id"))
    if R["unificar_dispositivos"]:
        mapping, f = devices.unify(t["dispositivos"], s, ccfg["dispositivos"]["folga_troca_dias"])
        s, r = devices.apply(s, mapping), devices.apply(r, mapping)
        fl.append(f)
    if R["dedup_uso"]:
        s, f1 = dedup.dedup_usage(s, ccfg["dedup"]["uso_chave_sessao"], "sessao_id", "sessoes_app")
        r, f2 = dedup.dedup_usage(r, ccfg["dedup"]["uso_chave_reproducao"], "reproducao_id", "reproducoes")
        fl += [f1, f2]
    if R["limites_fisicos"]:
        r, s, f = usage_limits.apply_limits(r, s, ccfg["limites"])
        fl.append(f)
    r["dia_local"] = outliers.local_time(r["inicio_em"], r["conta_id"], tz).dt.floor("D")

    # ------------------------------------------------------------------ detectores (sinalizar)
    oc = ccfg["outliers"]
    pdays = outliers.perfil_day(r, tz)
    iqr = outliers.iqr_flags(pdays, oc["iqr_k"])
    mad = outliers.mad_flags(pdays, oc["mad_z"])
    daily = outliers.daily_series(pdays)
    seas = outliers.explain_days(outliers.seasonal_flags(daily, oc["sazonal_janela_dias"], oc["sazonal_z"]), r, t["episodios"])
    screens = t["assinaturas"].sort_values("iniciada_em").drop_duplicates("conta_id", keep="last").set_index("conta_id")["plano_id"].map(plan_screens(t["planos"]))
    feat = outliers.account_features(r, s, tz, screens)
    iso = outliers.isolation_forest(feat, oc["if_contaminacao"], oc["if_seed"])
    bots = set(iso.index[iso["explicacao"] == "robô"].get_level_values(0))
    sharing = set(iso.index[iso["explicacao"] == "compartilhamento acima do limite"].get_level_values(0))
    if R["bots"]:
        excluded |= bots
    fl += [
        F.make("outlier_iqr", "iqr_por_mes", "perfil_dia", pdays.loc[iqr].index, "sinalizar"),
        F.make("outlier_mad", "z_robusto_por_mes", "perfil_dia", pdays.loc[mad].index, "sinalizar"),
        F.make("dia_anomalo", "sazonal_explicado", "dia", range(len(seas)), "sinalizar", seas["explicacao"]),
        F.make("conta_robo", "isolation_forest", "contas", sorted(bots), "excluir_das_metricas" if R["bots"] else "sinalizar"),
        F.make("compartilhamento_acima_do_limite", "isolation_forest", "contas", sorted(sharing), "sinalizar"),
    ]
    drop_pd = pdays.loc[iqr, ["perfil_id", "dia"]] if R["outlier_como_erro"] else None
    if drop_pd is not None:
        fl.append(F.make("outlier_removido", "iqr_por_mes", "perfil_dia", drop_pd.index, "remover"))

    contracts += validate("clean", {"reproducoes": r, "pagamentos": t["pagamentos"], "timeline": tl}, raise_on_fail=strict)

    # ------------------------------------------------------------------ carga incremental do uso
    lc = ccfg["carga"]
    wh = Warehouse(run_dir / "warehouse")
    changed: set[str] = set()
    for name, key, df in (("sessoes_app", "sessao_id", s), ("reproducoes", "reproducao_id", r)):
        ch, late = wh.load(name, assign_batches(df, lc["lote_dias"], lc["janela_atrasados_dias"]), key)
        changed |= ch
        q.append(quarantine.entries(name, late[key], "atrasado_fora_da_janela"))

    # ------------------------------------------------------------------ clean (negócio) e marts
    t["sessoes_app"], t["reproducoes"] = s, r
    clean = {k: t[k] for k in ("contas", "perfis", "dispositivos", "assinaturas", "assinatura_eventos", "faturas", "pagamentos")}
    clean.update(linha_do_tempo=tl, periodos_conta=spans, dim_preco=dim_preco,
                 contas_excluidas=pd.DataFrame({"conta_id": sorted(excluded)}, dtype="int64"),
                 isolation_forest=iso.reset_index(), dias_anomalos=seas.reset_index(names="dia"))
    write_layer(clean, run_dir / "clean")
    pag = ccfg["churn"]["estados_pagantes"]
    m = {
        "mrr": marts.mrr(tl, t["faturas"], t["pagamentos"], excluded, pag),
        "assinantes": marts.subscribers_and_churn(spans, excluded),
        "coortes": marts.cohorts(spans, excluded),
    }
    m["engajamento"], recomputed = _engagement_incremental(wh, spans, excluded, drop_pd, run_dir)
    contracts += validate("marts", m, raise_on_fail=strict)
    write_layer(m, run_dir / "marts", clean=False)
    wh.save()

    flags = F.concat(fl)
    quar = pd.concat([x for x in q if len(x)], ignore_index=True) if any(len(x) for x in q) else pd.DataFrame(columns=quarantine.COLUMNS)
    write_table(flags, run_dir, "flags")
    write_table(quar, run_dir, "quarentena")
    rep["linhas"]["clean"] = {k: len(v) for k, v in clean.items()} | {"sessoes_app": len(s), "reproducoes": len(r)}
    rep["quarentena"] = quar.groupby(["tabela", "motivo"]).size().rename("linhas").reset_index().to_dict("records")
    rep["flags"] = flags.groupby(["regra", "tecnica", "acao"]).size().rename("linhas").reset_index().to_dict("records")
    rep["contratos"] = contracts
    rep["meses_particoes_alteradas"] = sorted(changed)
    rep["meses_engajamento_recalculados"] = recomputed
    rep["isolation_forest"] = iso["explicacao"].value_counts().to_dict()
    rep["dias_anomalos"] = seas["explicacao"].value_counts().to_dict()
    rep["contas_excluidas"] = len(excluded)
    (run_dir / "qualidade.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False, default=str))
    (run_dir / "qualidade.md").write_text(quality_markdown(rep))
    (run_dir / "execucao.json").write_text(json.dumps({"segundos": round(time.time() - t_start, 1)}))
    if verbose:
        print(f"[etl] {run_dir.name}: {len(flags):,d} marcações, {len(quar):,d} em quarentena, "
              f"{len(recomputed)} meses de engajamento recalculados ({time.time() - t_start:.0f}s)")
    return rep


def _engagement_incremental(wh: Warehouse, spans: pd.DataFrame, excluded: set[int], drop_pd: pd.DataFrame | None,
                            run_dir: Path) -> tuple[pd.DataFrame, list[str]]:
    """Recalcula o engajamento só dos meses cuja entrada mudou (partição, exclusões, base ativa)."""
    path = run_dir / "marts" / "engajamento.parquet"
    prev = pd.read_parquet(path).set_index("mes") if path.exists() else pd.DataFrame()
    ex_h = _h(sorted(excluded))
    rows, recomputed = [], []
    for p in marts.MONTHS:
        mes = str(p)
        e = marts.eom(p)
        act = spans[(spans["inicio"] <= e) & (spans["fim"] > e)]["conta_id"]
        dp = "" if drop_pd is None else _h(drop_pd[drop_pd["dia"].dt.to_period("M") == p].to_numpy().tolist())
        key = _h(wh.state["particoes"].get(f"reproducoes/{mes}"), ex_h, _h(sorted(act)), dp)
        if wh.state["marts"].get(mes) == key and mes in prev.index:
            rows.append({"mes": mes, **prev.loc[mes].to_dict()})
            continue
        plays = wh.read("reproducoes", {mes})
        drop = None if drop_pd is None else drop_pd.rename(columns={"dia": "dia_local"})
        rows.append(marts.engagement_month(plays, spans, excluded, mes, drop))
        wh.state["marts"][mes] = key
        recomputed.append(mes)
    return pd.DataFrame(rows), recomputed


def quality_markdown(rep: dict) -> str:
    L = [f"# Relatório de qualidade — variante `{rep['variante']}`", ""]
    L += ["## Linhas por camada", "", "| Tabela | Raw | Staging | Clean |", "|---|---:|---:|---:|"]
    for k, v in rep["linhas"]["raw"].items():
        L.append(f"| {k} | {v:,d} | {rep['linhas']['staging'].get(k, 0):,d} | {rep['linhas']['clean'].get(k, 0):,d} |")
    L += ["", "## Contratos", "", "| Camada | Tabela | Verificação | Falhas |", "|---|---|---|---:|"]
    L += [f"| {c['camada']} | {c['tabela']} | {c['verificacao']} | {c['falhas']:,d} |" for c in rep["contratos"]]
    L += ["", "## Quarentena", "", "| Tabela | Motivo | Linhas |", "|---|---|---:|"]
    L += [f"| {x['tabela']} | {x['motivo']} | {x['linhas']:,d} |" for x in rep["quarentena"]]
    L += ["", "## Marcações por regra", "", "| Regra | Técnica | Ação | Linhas |", "|---|---|---|---:|"]
    L += [f"| {x['regra']} | {x['tecnica']} | {x['acao']} | {x['linhas']:,d} |" for x in rep["flags"]]
    L += ["", "## Nulos: mecanismo antes de imputar", "", "| Coluna | % nulos | Mecanismo | Depende de | Grupo mais afetado |",
          "|---|---:|---|---|---|"]
    L += [f"| {x['coluna']} | {x['pct_nulos']} | {x['mecanismo']} | {x.get('depende_de', '')} | {x.get('grupo_mais_afetado', '') or ''} |"
          for x in rep["nulos"]]
    L += ["", "## Padronização (staging)", ""] + [f"- {k}: {v:,d}" for k, v in rep["padronizacao"].items()]
    L += ["", f"Meses de engajamento recalculados nesta execução: {len(rep['meses_engajamento_recalculados'])}", ""]
    return "\n".join(L)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "etl"
    cfg = settings()
    if cmd == "etl":
        run_etl(cfg["paths"]["raw"], cfg["paths"]["runs"] / "limpo", persist_staging=True)
    elif cmd == "evaluate":
        from dq.evaluate.run import evaluate
        evaluate()
    elif cmd == "report":
        from dq.report.dashboard import build
        build()
    else:
        raise SystemExit(f"comando desconhecido: {cmd}")


if __name__ == "__main__":
    main()
