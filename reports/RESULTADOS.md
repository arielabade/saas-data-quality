# Resultados (gerado por `make evaluate`)

Números da execução atual. A leitura e as decisões estão no README e em docs/.

## Quanto da base estava suja

| Tabela | Linhas no raw | Com defeito | % | Tipos |
|---|---:|---:|---:|---|
| contas | 6,055 | 1,393 | 23,01% | bot, conta_teste, nulo_uf_tv |
| reproducoes | 1,247,180 | 101,376 | 8,13% | atrasado, bot, fuso_misturado, orfao, relogio_errado, replay_lote, sessao_absurda, tempo_maior_que_conteudo, tempo_negativo |
| pagamentos | 69,014 | 3,299 | 4,78% | assinatura_sobreposta, orfao, preco_divergente, retentativa_duplicada, webhook_duplicado |
| sessoes_app | 1,081,672 | 41,214 | 3,81% | atrasado, fuso_misturado, orfao, relogio_errado, replay_lote |
| dispositivos | 15,305 | 258 | 1,69% | troca_dispositivo |
| faturas | 61,503 | 1,030 | 1,67% | assinatura_sobreposta, preco_divergente |
| assinatura_eventos | 26,051 | 193 | 0,74% | assinatura_sobreposta, evento_fora_de_ordem |
| assinaturas | 7,047 | 43 | 0,61% | assinatura_sobreposta |

## Precisão e recall por técnica

Precisão = acertos / (acertos + falsos positivos + legítimos derrubados). Achados nativos (já existiam na base de referência) não contam como erro da técnica.

| Grupo | Técnica | Unidade | Marcados | Precisão | Recall | Legítimos derrubados | Nativos |
|---|---|---|---:|---:|---:|---:|---:|
| cadastro | Regras de cadastro (contas internas) | linha | 75 | 100.0% | 97.5% | 0 | 36 |
| cadastro | Integridade referencial (quarentena) | linha | 2,380 | 100.0% | 100.0% | 0 | 0 |
| cobranca | Chave idempotente + janela (pagamentos) | linha | 2,396 | 99.2% | 100.0% | 0 | 299 |
| cobranca | SCD2: preço vigente na data | linha | 672 | 99.7% | 100.0% | 0 | 0 |
| assinatura | Máquina de estados (ordem dos eventos) | linha | 152 | 98.7% | 100.0% | 0 | 0 |
| assinatura | Intervalos por conta (sobreposição) | linha | 43 | 100.0% | 100.0% | 0 | 0 |
| uso | Chave natural (replay de lote) | linha | 6,637 | 100.0% | 100.0% | 0 | 4 |
| uso | Contrato de formato (fuso misturado) | linha | 23,696 | 100.0% | 100.0% | 0 | 0 |
| uso | Desvio por aparelho (relógio errado) | linha | 22,237 | 100.0% | 100.0% | 0 | 0 |
| uso | Sequência sem sobreposição (troca de ID) | linha | 240 | 99.6% | 89.9% | 0 | 7 |
| uso | Regra física (por reprodução) | linha | 78,276 | 96.6% | 100.0% | 182 | 70,324 |
| outlier de uso | IQR por mês (Q3 + 3·IQR) | perfil-dia | 20,645 | 88.3% | 54.7% | 590 | 15,486 |
| outlier de uso | Z-score robusto (mediana/MAD) | perfil-dia | 33,760 | 84.7% | 63.1% | 908 | 27,559 |
| outlier de uso | Regra física (≤ duração, ≤ 24 h/aparelho) | perfil-dia | 14,640 | 88.7% | 71.2% | 53 | 7,951 |
| série diária | Z-score no total diário (sem sazonalidade) | dia | 1 | 100.0% | 33.3% | 0 | 0 |
| série diária | Sazonal (tendência + dia da semana) | dia | 17 | 33.3% | 100.0% | 4 | 8 |
| série diária | Sazonal + calendário de estreias e feriados | dia | 13 | 60.0% | 100.0% | 0 | 8 |
| padrão por conta | Isolation Forest (qualquer anomalia) | conta | 157 | 68.2% | 100.0% | 4 | 91 |
| padrão por conta | Isolation Forest + explicação (robô / telas) | conta | 119 | 75.0% | 100.0% | 2 | 59 |
| padrão por conta | Regra simples: telas acima do limite | conta | 216 | 40.0% | 66.7% | 5 | 141 |
| padrão por conta | Regra simples: > 15 reproduções curtas/dia | conta | 26 | 100.0% | 33.3% | 0 | 11 |

Imputação da região (UF nula em cadastro pela TV): 1,331 de 1,338 contas imputadas (99.5%), acerto de 99.8%.

## Impacto no negócio: erro médio contra a verdade (jan/2024 a out/2026)

| Variante | MRR | Assinantes ativos | Churn mensal (p.p.) | Horas por assinante |
|---|---:|---:|---:|---:|
| ingenua | +4,04% | +3,63% | -0,14 | +5,08% |
| limpa | +0,01% | +0,01% | -0,00 | +0,15% |
| janela_0 | +0,01% | +0,01% | -0,00 | -2,78% |
| outlier_como_erro | +0,01% | +0,01% | -0,00 | -12,02% |
| sem_bots | +0,01% | +0,01% | -0,00 | +0,15% |
| sem_contas_internas | +0,43% | +0,89% | +0,01 | -0,14% |
| sem_dedup_pagamentos | +3,01% | +0,01% | -0,00 | +0,15% |
| sem_dedup_uso | +0,01% | +0,01% | -0,00 | +0,39% |
| sem_fuso_e_relogio | +0,01% | +0,01% | -0,00 | -0,03% |
| sem_limites_fisicos | +0,01% | +0,01% | -0,00 | +7,56% |
| sem_maquina_estados | +0,02% | +2,42% | -0,15 | -2,15% |
| sem_preco_scd | -0,07% | +0,01% | -0,00 | +0,15% |
| sem_quarentena_orfaos | +0,01% | +0,01% | -0,00 | +0,14% |
| sem_sobreposicao_assinaturas | +0,36% | +0,01% | -0,00 | +0,15% |
| sem_unificar_dispositivos | +0,01% | +0,01% | -0,00 | +0,15% |

## Decisões erradas e o que custam

Pipeline completo com UMA regra desligada. Métrica = a que essa decisão mais move em relação à limpeza completa.

| Decisão | Métrica mais afetada | Erro médio vs verdade | Efeito vs limpa | Pior mês |
|---|---|---:|---:|---|
| Nenhuma limpeza (só padronizar formato) | Horas por assinante | +5,08 % | +4,93 % | 2026-10 (+10,5 %) |
| Não filtrar contas internas e de teste | Assinantes ativos | +0,89 % | +0,88 % | 2026-07 (+1,5 %) |
| Não excluir robôs | MRR | +0,01 % | +0,00 % | 2026-03 (+0,0 %) |
| Não pôr órfãos em quarentena | Horas por assinante | +0,14 % | -0,00 % | 2024-05 (+0,3 %) |
| Não deduplicar webhook de pagamento | MRR | +3,01 % | +3,01 % | 2026-01 (+4,5 %) |
| Não deduplicar replay de lote | Horas por assinante | +0,39 % | +0,24 % | 2025-06 (+3,4 %) |
| Não corrigir fuso e relógio | Horas por assinante | -0,03 % | -0,18 % | 2024-06 (-0,3 %) |
| Não unificar IDs de aparelho | MRR | +0,01 % | +0,00 % | 2026-03 (+0,0 %) |
| Não aplicar limites físicos | Horas por assinante | +7,56 % | +7,41 % | 2026-10 (+15,4 %) |
| Usar eventos de assinatura como vieram | Assinantes ativos | +2,42 % | +2,41 % | 2026-10 (+3,8 %) |
| Não resolver assinaturas sobrepostas | MRR | +0,36 % | +0,35 % | 2026-08 (+1,3 %) |
| Não conferir preço com o SCD | MRR | -0,07 % | -0,08 % | 2025-09 (-0,1 %) |
| Remover outliers de IQR como se fossem erro | Horas por assinante | -12,02 % | -12,17 % | 2026-10 (-31,3 %) |
| Descartar eventos atrasados (janela 0) | Horas por assinante | -2,78 % | -2,92 % | 2025-05 (-3,3 %) |

## Retenção por coorte

| Variante | k | Retenção média |
|---|---:|---:|
| verdade | 3 | 80.3% |
| verdade | 6 | 71.7% |
| verdade | 12 | 55.4% |
| ingenua | 3 | 81.2% |
| ingenua | 6 | 72.9% |
| ingenua | 12 | 57.2% |
| limpa | 3 | 80.3% |
| limpa | 6 | 71.7% |
| limpa | 12 | 55.4% |

## Modelo de churn: viés das features sem limpeza

| Feature | Verdade (média) | Limpa | Ingênua | Viés ingênua |
|---|---:|---:|---:|---:|
| Meses de casa | 9,06 | 9,06 | 9,08 | +0,2% |
| Falhas de pagamento (90 d) | 0,15 | 0,15 | 0,15 | +5,1% |
| Horas assistidas (30 d) | 14,26 | 14,27 | 15,40 | +8,0% |
| Dias sem uso | 6,61 | 6,62 | 6,76 | +2,1% |
| Aparelhos (90 d) | 2,16 | 2,16 | 2,17 | +0,3% |
| Reproduções (30 d) | 15,82 | 15,82 | 15,85 | +0,2% |

| Variante | AUC (teste, dados reais) | AUC (teste, mesma fonte) | Churn previsto pelo modelo real | Churn real |
|---|---:|---:|---:|---:|
| verdade | 0.716 | 0.716 | 15.75% | 13.48% |
| limpa | 0.716 | 0.716 | 15.75% | 13.48% |
| ingenua | 0.716 | 0.715 | 15.76% | 13.48% |

## Carga incremental e atrasados

| Passo | Partições alteradas (meses) | Meses de engajamento recalculados |
|---|---|---|
| carga até 31/08/2026 | 2023-10, 2023-11, 2023-12, 2024-01, 2024-02, 2024-03, 2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-03, 2025-04, 2025-05, 2025-06, 2025-07, 2025-08, 2025-09, 2025-10, 2025-11, 2025-12, 2026-01, 2026-02, 2026-03, 2026-04, 2026-05, 2026-06, 2026-07, 2026-08 | 37: 2026-05, 2026-06, 2026-07, 2026-08, 2026-09, 2026-10 |
| +1 semana de lotes | 2026-08, 2026-09 | 2: 2026-08, 2026-09 |
| mesma semana de novo | nenhum | 0: — |

| Variante | Atrasados injetados | Em quarentena | Incorporados |
|---|---:|---:|---:|
| limpa | 16,723 | 0 | 100,0% |
| janela_0 | 16,723 | 14,466 | 13,5% |

## Escalas para tempo assistido (horas por perfil-dia)

| Escala | Assimetria | Curtose | % no primeiro décimo da faixa |
|---|---:|---:|---:|
| original | 6,80 | 71,7 | 95,6% |
| min_max | 6,80 | 71,7 | 95,6% |
| z_score | 6,80 | 71,7 | 95,6% |
| robusta | 6,80 | 71,7 | 95,6% |
| log1p | 1,24 | 3,3 | 23,1% |
| yeo_johnson | 0,03 | -0,3 | 6,2% |

## Nulos: mecanismo

| Coluna | % nulos | Mecanismo | Depende de |
|---|---:|---|---|
| uf | 22.28 | MAR | primeiro_aparelho |
| telefone | 7.63 | compatível com MCAR |  |
| data_nascimento | 11.92 | compatível com MCAR |  |
| cep | 5.19 | compatível com MCAR |  |
