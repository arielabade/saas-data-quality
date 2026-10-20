"""Relatório de qualidade e dashboard estático (make report).

Papel: transformar reports/resultados/resultados.json num dashboard HTML + Plotly para o GitHub
       Pages, com títulos que dizem a conclusão (gerados dos números, nunca escritos à mão), e
       copiar o relatório de qualidade da execução limpa para reports/.
Entrada: reports/resultados/{resultados.json,series.csv}, data/runs/limpo/qualidade.md.
Saída: docs/dashboard/index.html e reports/QUALIDADE.md.
Dependências: pandas.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from dq.config import ROOT, settings

TEMPLATE = Path(__file__).parent / "assets" / "dashboard.html"
OUT = ROOT / "docs" / "dashboard" / "index.html"  # o perfil ci grava em <reports>/dashboard


def br(x: float, d: int = 1) -> str:
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def sbr(x: float, d: int = 1) -> str:
    if round(x, d) == 0:
        return br(0.0, d)
    return ("+" if x > 0 else "") + br(x, d)


def ibr(n: int) -> str:
    return f"{n:,d}".replace(",", ".")


def money(cents: float) -> str:
    return "R$ " + br(cents / 100, 0)


def _err(r: dict, v: str, m: str) -> dict:
    return next(x for x in r["erros"] if x["variante"] == v and x["metrica"] == m)


def _det(r: dict, name_start: str) -> dict:
    return next(x for x in r["deteccao"] if x["tecnica"].startswith(name_start))


def series_block(series: pd.DataFrame, r: dict) -> dict:
    out = {}
    spec = {"mrr": ("MRR (R$)", "MRR", 0, "", 1 / 100), "ativos": ("Assinantes ativos", "Assinantes", 0, "", 1),
            "churn": ("Churn mensal (%)", "Churn", 2, "%", 100), "horas": ("Horas por assinante no mês", "Engajamento", 1, "", 1)}
    for k, (label, btn, dec, suf, mult) in spec.items():
        g = series[(series["metrica"] == k) & series["variante"].isin(["verdade", "ingenua", "limpa"])]
        w = g.pivot(index="mes", columns="variante", values="valor").sort_index() * mult
        ei, el = _err(r, "ingenua", k), _err(r, "limpa", k)
        unit = "p.p." if k == "churn" else "%"
        leitura = (f"Sem limpeza, o erro médio contra a verdade é de <b>{sbr(ei['erro_medio'], 2)} {unit}</b> "
                   f"(pior mês: {ei['pior_mes']}, {sbr(ei['erro_pior_mes'], 1)} {unit}). "
                   f"Com limpeza, cai para <b>{sbr(el['erro_medio'], 2)} {unit}</b>.")
        out[k] = {"meses": list(w.index), "verdade": w["verdade"].round(4).tolist(), "ingenua": w["ingenua"].round(4).tolist(),
                  "limpa": w["limpa"].round(4).tolist(), "label": label, "botao": btn, "dec": dec, "suf": suf, "leitura": leitura}
    return out


def build_data(r: dict, series: pd.DataFrame) -> dict:
    mrr_i, mrr_l = _err(r, "ingenua", "mrr"), _err(r, "limpa", "mrr")
    ch_i, ch_l = _err(r, "ingenua", "churn"), _err(r, "limpa", "churn")
    h_i = _err(r, "ingenua", "horas")
    at_i = _err(r, "ingenua", "ativos")
    s = pd.DataFrame(r["base_suja"])
    s = s[s["linhas_com_defeito"] > 0]
    total_pct = 100 * s["linhas_com_defeito"].sum() / s["linhas_raw"].sum()
    top = s.sort_values("pct", ascending=False).iloc[0]
    det = pd.DataFrame(r["deteccao"])
    rules = det[det["unidade"] == "linha"]
    good = rules[(rules["precisao"] >= 0.95) & (rules["recall"] >= 0.95)]
    iqr, mad, phys = _det(r, "IQR"), _det(r, "Z-score robusto"), _det(r, "Regra física (≤")
    seas_e, naive_d = _det(r, "Sazonal + calendário"), _det(r, "Z-score no total")
    iso_x, iso_any = _det(r, "Isolation Forest + explicação"), _det(r, "Isolation Forest (qualquer")
    wrong = {x["variante"]: x for x in r["decisoes_erradas"]}
    oe = wrong.get("outlier_como_erro", {})
    dd = wrong.get("sem_dedup_pagamentos", {})
    cm = r["churn_modelo"]
    perf = {x["variante"]: x for x in cm["desempenho"]}
    vies = pd.DataFrame(cm["vies"])
    vi = vies[vies["variante"] == "ingenua"].assign(a=lambda d: d["vies_pct"].abs()).sort_values("a", ascending=False)
    mrr_last = series[(series["metrica"] == "mrr") & (series["variante"] == "verdade")].sort_values("mes")["valor"].iloc[-1]
    mrr_gap = abs(mrr_i["erro_ultimo_mes"]) / 100 * mrr_last

    textos = {
        "h-headline": (f"Sem limpeza, o MRR sai <span class='hl'>{sbr(mrr_i['erro_medio'], 1)}%</span> e o engajamento "
                       f"<span class='hl'>{sbr(h_i['erro_medio'], 1)}%</span> fora da verdade"),
        "bigidea": (f"Injetamos 17 tipos de defeito realistas numa base de streaming por assinatura e registramos cada um. "
                    f"{len(good)} das {len(rules)} regras por linha acertam acima de 95% em precisão e recall. "
                    f"A armadilha está nos detectores estatísticos: o IQR derrubou {ibr(iqr['legitimos_derrubados'])} perfil-dias "
                    f"legítimos (maratonas de estreia, usuários intensos). A combinação recomendada deixa o MRR a "
                    f"{br(abs(mrr_l['erro_medio']), 2)}% da verdade."),
        "h-dirty": f"{br(total_pct, 1)}% das linhas tinham ao menos um defeito; em {top['tabela']}, {br(top['pct'], 1)}%",
        "r-dirty": ("Percentual de linhas de cada tabela da camada raw tocadas por um defeito injetado. Uso (sessões e "
                    "reproduções) concentra o volume; cobrança concentra o impacto em dinheiro."),
        "h-tech": ("Regras de negócio acertam quase tudo; outlier estatístico confunde erro com cliente engajado"),
        "r-tech": ("Precisão: dos marcados, quantos eram defeito (legítimo derrubado conta como erro). Recall: dos defeitos, "
                   "quantos foram pegos. Achados que já existiam na base de referência (nativos) aparecem à parte."),
        "h-real": (f"O modelo sazonal pega {seas_e['acertos']} de {seas_e['defeitos_alvo']} dias de replay sem derrubar "
                   f"estreia nem feriado; o z-score simples pega {naive_d['acertos']}"),
        "r-real": ("Total diário de horas assistidas na base suja. O z-score simples marca qualquer pico (inclusive crescimento "
                   "e estreias). O modelo sazonal compara com tendência e dia da semana e, antes de chamar de erro, procura "
                   "uma estreia ou feriado que explique o pico."),
        "h-compose": (f"IQR e z-score robusto derrubam {ibr(iqr['legitimos_derrubados'])} e {ibr(mad['legitimos_derrubados'])} "
                      f"perfil-dias legítimos; a regra física, {ibr(phys['legitimos_derrubados'])}"),
        "r-compose": ("Composição de tudo que cada detector marcou. Cobalt é defeito de verdade; vermelho é cliente real "
                      "tratado como erro. Isolation Forest só ganha precisão quando a anomalia é explicada (robô ou telas acima do limite)."),
        "h-impact": (f"A limpeza tira o MRR de {sbr(mrr_i['erro_medio'], 1)}% para {sbr(mrr_l['erro_medio'], 2)}% "
                     f"e o churn de {sbr(ch_i['erro_medio'], 2)} para {sbr(ch_l['erro_medio'], 2)} p.p."),
        "h-wrong": (f"Não deduplicar o webhook infla o MRR em {sbr(dd.get('erro_mrr', 0), 1)}%; tratar maratona como erro "
                    f"tira {br(abs(oe.get('erro_horas', 0)), 1)}% do engajamento"),
        "r-wrong": ("Cada barra é o pipeline completo com UMA decisão errada, comparado com a verdade, na métrica que ela mais "
                    "distorce (erro médio de jan/2024 a out/2026)."),
        "h-model": (f"Num modelo de churn, a feature mais enviesada sem limpeza é “{vi.iloc[0]['rotulo']}” "
                    f"({sbr(vi.iloc[0]['vies_pct'], 0)}%)"),
        "r-model": (f"Mesmo rótulo e mesma população; só as features mudam. AUC fora do tempo, aplicado a dados reais: "
                    f"{br(perf['verdade']['auc_teste_dados_reais'], 3)} treinando na verdade, "
                    f"{br(perf['limpa']['auc_teste_dados_reais'], 3)} na base limpa e "
                    f"{br(perf['ingenua']['auc_teste_dados_reais'], 3)} na base suja."),
        "h-rec": "Regras de negócio primeiro; estatística só para sinalizar",
        "r-rec": (f"No último mês, o MRR sem limpeza erra {money(mrr_gap)} por mês. O custo de cada erro define a ação: "
                  "o que infla receita sai do número; o que parece estranho mas é cliente fica, sinalizado."),
    }
    kpis = [
        {"v": br(total_pct, 1) + "%", "l": "das linhas com defeito injetado"},
        {"v": sbr(mrr_i["erro_medio"], 1) + "%", "l": f"erro médio do MRR sem limpeza (com limpeza: {sbr(mrr_l['erro_medio'], 2)}%)", "hl": True},
        {"v": sbr(ch_i["erro_medio"], 2) + " p.p.", "l": f"erro médio do churn mensal sem limpeza (com: {sbr(ch_l['erro_medio'], 2)})"},
        {"v": sbr(at_i["erro_medio"], 1) + "%", "l": "assinantes ativos inflados sem limpeza"},
    ]
    rec = [
        f"<b>Deduplicar cobrança por chave idempotente e janela de 1 h</b> antes de qualquer soma: sem isso o MRR sobe "
        f"{sbr(dd.get('erro_mrr', 0), 1)}%. Custo de errar para mais: receita reportada que não existe.",
        "<b>Reconstruir a assinatura como máquina de estados</b> e resolver sobreposição por conta: churn e base ativa "
        "dependem da ordem dos eventos, não do status da foto.",
        "<b>Tirar contas internas, de teste e robôs</b> das métricas (sem apagar: o financeiro reconcilia).",
        "<b>Aplicar limites físicos</b> (≤ duração do conteúdo, ≤ 24 h por aparelho no dia) e corrigir fuso e relógio "
        "pela hora do servidor: é o que tira o engajamento impossível.",
        f"<b>Usar IQR, z-score e Isolation Forest só para sinalizar</b>, nunca para remover: tratar outlier como erro tira "
        f"{br(abs(oe.get('erro_horas', 0)), 1)}% das horas no mês. Isolation Forest vale quando a anomalia vem com explicação "
        f"(precisão {br(100 * iso_x['precisao'], 0)}% contra {br(100 * iso_any['precisao'], 0)}% sem explicação).",
        "<b>Carga incremental com janela de atrasados de 30 dias</b>: o celular offline entra no mês certo e só os meses "
        "afetados são recalculados.",
    ]
    metodo = method_html(r)
    grupos = list(dict.fromkeys(det["grupo"]))
    return {"textos": textos, "kpis": kpis, "recomendacao": rec, "metodo": metodo, "base_suja": r["base_suja"],
            "deteccao": r["deteccao"], "grupos": grupos, "serie_diaria": r["serie_diaria"],
            "series": series_block(series, r), "metricas": ["mrr", "ativos", "churn", "horas"],
            "decisoes_erradas": r["decisoes_erradas"], "modelo": {"vies": [x for x in cm["vies"] if x["variante"] != "verdade"]}}


def method_html(r: dict) -> str:
    reg = pd.DataFrame(r["registro"])
    rows = "".join(f"<tr><td>{x.tipo}</td><td>{x.categoria}</td><td>{x.linhas:,}</td></tr>".replace(",", ".")
                   for x in reg.sort_values(["categoria", "linhas"], ascending=[True, False]).itertuples())
    inc = "".join(f"<li><b>{s['passo']}</b>: partições alteradas {', '.join(s['meses_particao_alterados']) or 'nenhuma'}; "
                  f"{len(s['meses_engajamento_recalculados'])} meses de engajamento recalculados.</li>" for s in r["incremental"]["passos"])
    esc = "".join(f"<tr><td>{x['escala']}</td><td>{br(x['assimetria'], 2)}</td><td>{br(x['pct_no_primeiro_decimo'], 1)}%</td></tr>"
                  for x in r["escalas"])
    nul = "".join(f"<li><b>{x['coluna']}</b>: {x['pct_nulos']}% nulos, {x['mecanismo']}"
                  f"{' (depende de ' + x['depende_de'] + ')' if x.get('depende_de') else ''}.</li>" for x in r["nulos"])
    im = r["imputacao"]
    return f"""
<h3>Como os dados foram montados</h3>
<p>Base sintética de um streaming por assinatura (≈6 mil contas, out/2023 a out/2026) carregada num MySQL e extraída como
referência. Um injetor copia a base e aplica defeitos com semente fixa, gravando cada alteração num registro (tabela, chave,
coluna, tipo, valor original, valor sujo). Outliers verdadeiros (maratona de estreia, usuários intensos, pico de feriado,
compartilhamento pago) entram na referência e na base suja, marcados como legítimos. O ETL nunca lê o registro: um teste
falha se ler.</p>
<h3>Como cada técnica foi medida</h3>
<p>Precisão = acertos / (acertos + falsos positivos + legítimos derrubados). Recall = acertos / defeitos que a técnica
deveria pegar. A base de referência já tinha imperfeições próprias (milissegundos no app 6.x, perfis tocando ao mesmo tempo
na mesma TV, contas de QA); o que a técnica marca também nela é contado como <i>nativo</i>, não como erro.</p>
<h3>Como o impacto foi medido</h3>
<p>“Verdade” é a base sem defeitos passando pelo mesmo pipeline. Cada variante (sem limpeza, limpa, e uma ablação por regra)
é comparada com ela mês a mês. MRR: soma, nas assinaturas pagantes no fim do mês, do valor recebido da fatura que cobre o dia,
normalizado ao mês. Churn: contas que deixam de ter assinatura vigente no mês, com 7 dias de carência para reativação, sobre
as vigentes no início do mês.</p>
<h3>Registro de defeitos</h3>
<div class="table-wrap"><table><thead><tr><th>Tipo</th><th>Categoria</th><th>Linhas</th></tr></thead><tbody>{rows}</tbody></table></div>
<h3>Carga incremental</h3><ul>{inc}</ul>
<h3>Nulos: mecanismo antes de imputar</h3><ul>{nul}</ul>
<p>Região imputada pela moda das sessões da conta: {im['imputados']:,} contas, acerto de {br(100 * im['acerto_regiao'], 1)}%.</p>
<h3>Escalas para tempo assistido (horas por perfil-dia)</h3>
<div class="table-wrap"><table><thead><tr><th>Escala</th><th>Assimetria</th><th>No primeiro décimo da faixa</th></tr></thead><tbody>{esc}</tbody></table></div>
<p>Min-max e z-score não mudam a forma: a cauda espreme quase tudo perto de zero. Log1p e Yeo-Johnson aproximam a simetria;
são as escolhas para modelos lineares e distâncias.</p>
"""


def build() -> None:
    cfg = settings()
    res = cfg["paths"]["reports"] / "resultados"
    r = json.loads((res / "resultados.json").read_text())
    series = pd.read_csv(res / "series.csv", dtype={"mes": str})
    data = build_data(r, series)
    html = TEMPLATE.read_text().replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, default=str))
    out = OUT if cfg["profile"] == "full" else cfg["paths"]["reports"] / "dashboard" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    (out.parent / ".nojekyll").write_text("")
    q = cfg["paths"]["runs"] / "limpo" / "qualidade.md"
    if q.exists():
        shutil.copy(q, cfg["paths"]["reports"] / "QUALIDADE.md")
    print(f"[report] dashboard em {out}")
