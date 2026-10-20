# Relatório de qualidade — variante `limpo`

## Linhas por camada

| Tabela | Raw | Staging | Clean |
|---|---:|---:|---:|
| canais | 6 | 6 | 0 |
| planos | 3 | 3 | 0 |
| precos | 20 | 20 | 0 |
| contas | 6,055 | 6,055 | 6,055 |
| perfis | 15,696 | 15,696 | 15,696 |
| dispositivos | 15,305 | 15,305 | 15,305 |
| assinaturas | 7,047 | 7,047 | 7,004 |
| assinatura_eventos | 26,051 | 26,051 | 26,051 |
| faturas | 61,503 | 61,503 | 61,143 |
| pagamentos | 69,014 | 69,014 | 66,118 |
| titulos | 3,000 | 3,000 | 0 |
| episodios | 24,236 | 24,236 | 0 |
| sessoes_app | 1,081,672 | 1,081,672 | 1,077,981 |
| reproducoes | 1,247,180 | 1,247,180 | 1,241,973 |

## Contratos

| Camada | Tabela | Verificação | Falhas |
|---|---|---|---:|
| raw | pagamentos | todas | 0 |
| raw | reproducoes | segundos_assistidos: tempo assistido negativo | 2,361 |
| raw | contas | uf: not_nullable | 1,349 |
| raw | contas | uf: str_matches('^[A-Z]{2}$') | 150 |
| staging | faturas | todas | 0 |
| staging | pagamentos | todas | 0 |
| staging | reproducoes | todas | 0 |
| staging | dispositivos | todas | 0 |
| clean | pagamentos | todas | 0 |
| clean | reproducoes | todas | 0 |
| clean | timeline | todas | 0 |
| marts | mrr | todas | 0 |
| marts | assinantes | todas | 0 |
| marts | engajamento | todas | 0 |

## Quarentena

| Tabela | Motivo | Linhas |
|---|---|---:|
| assinatura_eventos | assinatura_sobreposta | 43 |
| assinaturas | assinatura_sobreposta | 43 |
| faturas | assinatura_sobreposta | 360 |
| pagamentos | assinatura_sobreposta | 360 |
| pagamentos | fatura_inexistente | 138 |
| reproducoes | perfil_inexistente | 1,161 |
| sessoes_app | perfil_inexistente | 1,081 |

## Marcações por regra

| Regra | Técnica | Ação | Linhas |
|---|---|---|---:|
| assinatura_sobreposta | intervalos_por_conta | quarentena | 43 |
| chegada_atrasada | recebido_menos_ocorrido | sinalizar | 17,505 |
| compartilhamento_acima_do_limite | isolation_forest | sinalizar | 79 |
| conta_interna | regras_de_cadastro | excluir_das_metricas | 100 |
| conta_robo | isolation_forest | excluir_das_metricas | 26 |
| dia_anomalo | sazonal_explicado | sinalizar | 35 |
| dispositivo_unificado | sequencia_sem_sobreposicao | corrigir | 240 |
| evento_desvio_relogio | tolerancia_24h | corrigir | 116 |
| evento_fora_de_ordem | maquina_de_estados+cabecalho | corrigir | 152 |
| fuso_misturado | contrato_de_formato | corrigir | 23,962 |
| mais_de_24h_por_aparelho | regra_fisica | limitar | 69,046 |
| orfao | integridade_referencial | quarentena | 2,380 |
| outlier_iqr | iqr_por_mes | sinalizar | 17,158 |
| outlier_mad | z_robusto_por_mes | sinalizar | 30,788 |
| pagamento_duplicado | chave_idempotente+janela | remover | 2,398 |
| preco_divergente | scd2_vigente_na_data | corrigir | 1,392 |
| regiao_imputada | moda_das_sessoes_da_conta | imputar | 1,338 |
| relogio_errado | desvio_por_aparelho | corrigir | 18,519 |
| relogio_zerado | hora_do_servidor | corrigir | 3,826 |
| sessao_aberta_demais | regra_fisica | corrigir | 2,481 |
| sessao_nao_recebida | chave_logica | sinalizar | 2,874 |
| tempo_maior_que_conteudo | regra_fisica | limitar | 8,655 |
| tempo_negativo | regra_fisica | corrigir | 1,774 |
| tempo_negativo_sem_horario | regra_fisica | sinalizar | 570 |
| transicao_invalida | maquina_de_estados | sinalizar | 98 |
| uso_duplicado | chave_natural | remover | 6,656 |

## Nulos: mecanismo antes de imputar

| Coluna | % nulos | Mecanismo | Depende de | Grupo mais afetado |
|---|---:|---|---|---|
| uf | 22.28 | MAR | primeiro_aparelho | tv (70% nulo vs 22% geral) |
| telefone | 7.63 | compatível com MCAR |  | nan |
| data_nascimento | 11.92 | compatível com MCAR |  | nan |
| cep | 5.19 | compatível com MCAR |  | nan |

## Padronização (staging)

- uf_padronizada: 150
- tipo_dispositivo_padronizado: 371
- sessoes_app_ts_sem_fuso: 12,056
- reproducoes_ts_sem_fuso: 11,930
- reproducoes_ms_convertidas: 269,832

Meses de engajamento recalculados nesta execução: 37
