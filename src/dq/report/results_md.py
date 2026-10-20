"""Leitura escrita dos resultados (reports/RESULTADOS.md), gerada a partir de resultados.json.

Papel: transformar os números da avaliação em tabelas legíveis no GitHub, sem edição manual.
Entrada: dicionário de resultados (dq.evaluate.run).
Saída: reports/RESULTADOS.md.
Dependências: nenhuma além da biblioteca padrão.
"""

from __future__ import annotations

from pathlib import Path


def _pct(x, nd=1) -> str:
    return "—" if x is None or x != x else f"{100 * x:.{nd}f}%"


def _num(x, nd=1, signed=False) -> str:
    if x is None or x != x:
        return "—"
    s = f"{x:+,.{nd}f}" if signed else f"{x:,.{nd}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def write_results_md(r: dict, path: Path) -> None:
    L = ["# Resultados (gerado por `make evaluate`)", "",
         "Números da execução atual. A leitura e as decisões estão no README e em docs/.", ""]

    L += ["## Quanto da base estava suja", "", "| Tabela | Linhas no raw | Com defeito | % | Tipos |", "|---|---:|---:|---:|---|"]
    for x in r["base_suja"]:
        if x["linhas_com_defeito"]:
            L.append(f"| {x['tabela']} | {x['linhas_raw']:,d} | {x['linhas_com_defeito']:,d} | {_num(x['pct'], 2)}% | {x['tipos']} |")

    L += ["", "## Precisão e recall por técnica", "",
          "Precisão = acertos / (acertos + falsos positivos + legítimos derrubados). Achados nativos (já existiam na base de "
          "referência) não contam como erro da técnica.", "",
          "| Grupo | Técnica | Unidade | Marcados | Precisão | Recall | Legítimos derrubados | Nativos |",
          "|---|---|---|---:|---:|---:|---:|---:|"]
    for x in r["deteccao"]:
        L.append(f"| {x['grupo']} | {x['tecnica']} | {x['unidade']} | {x['marcados']:,d} | {_pct(x['precisao'])} | "
                 f"{_pct(x['recall'])} | {x['legitimos_derrubados']:,d} | {x['nativos']:,d} |")
    im = r["imputacao"]
    L += ["", f"Imputação da região (UF nula em cadastro pela TV): {im['imputados']:,d} de {im['nulos_injetados']:,d} contas "
          f"imputadas ({_pct(im['cobertura'])}), acerto de {_pct(im['acerto_regiao'])}.", ""]

    L += ["## Impacto no negócio: erro médio contra a verdade (jan/2024 a out/2026)", "",
          "| Variante | MRR | Assinantes ativos | Churn mensal (p.p.) | Horas por assinante |", "|---|---:|---:|---:|---:|"]
    by = {}
    for x in r["erros"]:
        by.setdefault(x["variante"], {})[x["metrica"]] = x
    for v in ["ingenua", "limpa"] + [k for k in by if k not in ("ingenua", "limpa", "verdade")]:
        e = by.get(v)
        if not e:
            continue
        L.append(f"| {v} | {_num(e['mrr']['erro_medio'], 2, True)}% | {_num(e['ativos']['erro_medio'], 2, True)}% | "
                 f"{_num(e['churn']['erro_medio'], 2, True)} | {_num(e['horas']['erro_medio'], 2, True)}% |")

    L += ["", "## Decisões erradas e o que custam", "",
          "Pipeline completo com UMA regra desligada. Métrica = a que essa decisão mais move em relação à limpeza completa.", "",
          "| Decisão | Métrica mais afetada | Erro médio vs verdade | Efeito vs limpa | Pior mês |", "|---|---|---:|---:|---|"]
    for x in r["decisoes_erradas"]:
        L.append(f"| {x['decisao']} | {x['metrica_mais_afetada']} | {_num(x['erro_medio'], 2, True)} {x['unidade']} | "
                 f"{_num(x['efeito_vs_limpa'], 2, True)} {x['unidade']} | {x['pior_mes']} ({_num(x['erro_pior_mes'], 1, True)} {x['unidade']}) |")

    L += ["", "## Retenção por coorte", "", "| Variante | k | Retenção média |", "|---|---:|---:|"]
    L += [f"| {x['variante']} | {x['k']} | {_pct(x['retencao_media'])} |" for x in r["coortes"]]

    cm = r["churn_modelo"]
    L += ["", "## Modelo de churn: viés das features sem limpeza", "",
          "| Feature | Verdade (média) | Limpa | Ingênua | Viés ingênua |", "|---|---:|---:|---:|---:|"]
    vb = {(x["variante"], x["feature"]): x for x in cm["vies"]}
    for f in dict.fromkeys(x["feature"] for x in cm["vies"]):
        t, lp, ig = vb[("verdade", f)], vb[("limpa", f)], vb[("ingenua", f)]
        L.append(f"| {t['rotulo']} | {_num(t['media'], 2)} | {_num(lp['media'], 2)} | {_num(ig['media'], 2)} | {_num(ig['vies_pct'], 1, True)}% |")
    L += ["", "| Variante | AUC (teste, dados reais) | AUC (teste, mesma fonte) | Churn previsto pelo modelo real | Churn real |",
          "|---|---:|---:|---:|---:|"]
    L += [f"| {x['variante']} | {x['auc_teste_dados_reais']:.3f} | {x['auc_teste_mesma_fonte']:.3f} | "
          f"{_pct(x['churn_previsto_pelo_modelo_real'], 2)} | {_pct(x['churn_real_teste'], 2)} |" for x in cm["desempenho"]]

    L += ["", "## Carga incremental e atrasados", "", "| Passo | Partições alteradas (meses) | Meses de engajamento recalculados |", "|---|---|---|"]
    for s in r["incremental"]["passos"]:
        L.append(f"| {s['passo']} | {', '.join(s['meses_particao_alterados']) or 'nenhum'} | "
                 f"{len(s['meses_engajamento_recalculados'])}: {', '.join(s['meses_engajamento_recalculados'][-6:]) or '—'} |")
    L += ["", "| Variante | Atrasados injetados | Em quarentena | Incorporados |", "|---|---:|---:|---:|"]
    L += [f"| {x['variante']} | {x['atrasados']:,d} | {x['em_quarentena']:,d} | {_num(x['incorporados_pct'], 1)}% |" for x in r["atrasados"]]

    L += ["", "## Escalas para tempo assistido (horas por perfil-dia)", "", "| Escala | Assimetria | Curtose | % no primeiro décimo da faixa |", "|---|---:|---:|---:|"]
    L += [f"| {x['escala']} | {_num(x['assimetria'], 2)} | {_num(x['curtose'], 1)} | {_num(x['pct_no_primeiro_decimo'], 1)}% |" for x in r["escalas"]]

    L += ["", "## Nulos: mecanismo", "", "| Coluna | % nulos | Mecanismo | Depende de |", "|---|---:|---|---|"]
    L += [f"| {x['coluna']} | {x['pct_nulos']} | {x['mecanismo']} | {x.get('depende_de') or ''} |" for x in r["nulos"]]
    path.write_text("\n".join(L) + "\n")
