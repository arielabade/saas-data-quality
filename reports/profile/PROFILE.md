# Perfil de dados (gerado)

Gerado por `python -m dq.profile.profiler`. Não edite à mão: a leitura está em docs/DATA_SOURCE.md.

## Tabelas

| Tabela | Linhas | PK | PK duplicadas |
|---|---:|---|---:|
| `canais` | 6 | canal_id | 0 |
| `planos` | 3 | plano_id | 0 |
| `precos` | 20 | preco_id | 0 |
| `contas` | 6,000 | conta_id | 0 |
| `perfis` | 15,525 | perfil_id | 0 |
| `dispositivos` | 14,745 | dispositivo_id | 0 |
| `assinaturas` | 6,944 | assinatura_id | 0 |
| `assinatura_eventos` | 25,825 | evento_id | 0 |
| `faturas` | 60,835 | fatura_id | 0 |
| `pagamentos` | 66,090 | pagamento_id | 0 |
| `titulos` | 3,000 | titulo_id | 0 |
| `episodios` | 24,236 | episodio_id | 0 |
| `sessoes_app` | 1,046,532 | sessao_id | 0 |
| `reproducoes` | 1,168,273 | reproducao_id | 0 |

### `canais`

| Coluna | Tipo | Nulos % | Distintos | Resumo |
|---|---|---:|---:|---|
| canal_id | numerico | 0.00 | 6 | min 1.00 · p50 3.50 · p99 5.95 · max 6.00 |
| codigo | texto | 0.00 | 6 | organico: 1, busca_paga: 1, social_pago: 1, indicacao: 1, parceria_operadora: 1, tv: 1 |
| nome | texto | 0.00 | 6 | Orgânico: 1, Busca paga: 1, Social pago: 1, Indicação: 1, Parceria com operadora: 1, TV: 1 |
| tipo | texto | 0.00 | 4 | pago: 3, organico: 1, indicacao: 1, parceria: 1 |
| pago | flag | 0.00 | 2 | 0: 3, 1: 3 |

### `planos`

| Coluna | Tipo | Nulos % | Distintos | Resumo |
|---|---|---:|---:|---|
| plano_id | numerico | 0.00 | 3 | min 1.00 · p50 2.00 · p99 2.98 · max 3.00 |
| codigo | texto | 0.00 | 3 | basico_anuncios: 1, padrao: 1, premium: 1 |
| nome | texto | 0.00 | 3 | Básico com anúncios: 1, Padrão: 1, Premium: 1 |
| com_anuncios | flag | 0.00 | 2 | 0: 2, 1: 1 |
| resolucao_maxima | texto | 0.00 | 3 | 720p: 1, 1080p: 1, 4k: 1 |
| telas_simultaneas | flag | 0.00 | 2 | 2: 2, 4: 1 |
| max_perfis | flag | 0.00 | 1 | 5: 3 |
| permite_membro_extra | flag | 0.00 | 2 | 1: 2, 0: 1 |

### `precos`

| Coluna | Tipo | Nulos % | Distintos | Resumo |
|---|---|---:|---:|---|
| preco_id | numerico | 0.00 | 20 | min 1.00 · p50 10.50 · p99 19.81 · max 20.00 |
| plano_id | numerico | 10.00 | 3 | min 1.00 · p50 2.00 · p99 3.00 · max 3.00 |
| item | texto | 0.00 | 2 | assinatura: 18, membro_extra: 2 |
| periodicidade | texto | 0.00 | 2 | mensal: 11, anual: 9 |
| valor_brl | numerico | 0.00 | 20 | min 12.90 · p50 62.40 · p99 639.50 · max 649.00 |
| vigencia_inicio | data | 0.00 | 4 | 2023-01-01 → 2025-09-01 |
| vigencia_fim | data | 35.00 | 2 | 2024-07-31 → 2025-08-31 |

### `contas`

| Coluna | Tipo | Nulos % | Distintos | Resumo |
|---|---|---:|---:|---|
| conta_id | numerico | 0.00 | 6,000 | min 1.00 · p50 3,000.50 · p99 5,940.01 · max 6,000.00 |
| email | texto | 0.00 | 6,000 | top: eduarda_grande@mensagens (1), arthurpereira@provedor.e (1), gael_fernandes@mail.exam (1) |
| nome_titular | texto | 0.00 | 5,583 | top: Lunna Fonseca (4), Pietra Carvalho (4), Melissa Aragão (4) |
| cpf | texto | 0.00 | 6,000 | top: 098.432.571-97 (1), 150.897.634-10 (1), 317.506.942-80 (1) |
| telefone | texto | 7.67 | 5,540 | top: 38 92046-3977 (1), 41 95342-8123 (1), 35 98141-3457 (1) |
| data_nascimento | data | 11.88 | 4,351 | 1940-12-12 → 2008-09-24 |
| cep | texto | 5.18 | 5,689 | top: 69257-820 (1), 32788-618 (1), 30851806 (1) |
| cidade | texto | 0.00 | 2,171 | top: da Cunha (45), Pinto (43), Gomes (42) |
| uf | texto | 0.00 | 92 | top: SP (1305), MG (599), RJ (460) |
| criada_em | data_hora | 0.00 | 5,999 | 2023-10-01 03:11:13 → 2026-11-01 02:41:36 |
| canal_aquisicao_id | numerico | 0.00 | 6 | min 1.00 · p50 2.00 · p99 6.00 · max 6.00 |
| indicada_por_conta_id | numerico | 91.13 | 428 | min 2.00 · p50 1,150.00 · p99 5,132.86 · max 5,648.00 |
| aceita_marketing | flag | 0.00 | 2 | 1: 4,094, 0: 1,906 |

### `perfis`

| Coluna | Tipo | Nulos % | Distintos | Resumo |
|---|---|---:|---:|---|
| perfil_id | numerico | 0.00 | 15,525 | min 1.00 · p50 7,763.00 · p99 15,369.76 · max 15,525.00 |
| conta_id | numerico | 0.00 | 6,000 | min 1.00 · p50 2,984.00 · p99 5,941.76 · max 6,000.00 |
| nome | texto | 0.00 | 285 | top: Sala (493), Crianças (308), Pequenos (294) |
| infantil | flag | 0.00 | 2 | 0: 14,380, 1: 1,145 |
| principal | flag | 0.00 | 2 | 0: 9,525, 1: 6,000 |
| membro_extra | flag | 0.00 | 2 | 0: 15,379, 1: 146 |
| telemetria_detalhada | flag | 0.00 | 2 | 0: 14,752, 1: 773 |
| criado_em | data_hora | 0.00 | 15,524 | 2023-10-01 03:12:13 → 2026-11-01 02:42:36 |
| excluido_em | data_hora | 97.28 | 423 | 2023-12-13 01:39:17 → 2026-10-29 20:40:41 |

### `dispositivos`

| Coluna | Tipo | Nulos % | Distintos | Resumo |
|---|---|---:|---:|---|
| dispositivo_id | numerico | 0.00 | 14,745 | min 1.00 · p50 7,373.00 · p99 14,597.56 · max 14,745.00 |
| conta_id | numerico | 0.00 | 6,000 | min 1.00 · p50 2,993.00 · p99 5,942.56 · max 6,000.00 |
| tipo | texto | 0.00 | 16 | celular: 6,161, tv: 4,719, web: 2,196, tablet: 1,311, Celular: 53, smartphone: 52, tv : 47, mobile: 45 |
| plataforma | texto | 0.00 | 5 | mobile_os_a: 5,221, tv_os_a: 2,572, mobile_os_b: 2,429, tv_os_b: 2,269, web: 2,254 |
| registrado_em | data_hora | 0.00 | 14,743 | 2023-10-01 19:19:38 → 2026-10-31 23:50:44 |

### `assinaturas`

| Coluna | Tipo | Nulos % | Distintos | Resumo |
|---|---|---:|---:|---|
| assinatura_id | numerico | 0.00 | 6,944 | min 1.00 · p50 3,472.50 · p99 6,874.57 · max 6,944.00 |
| conta_id | numerico | 0.00 | 6,000 | min 1.00 · p50 2,769.50 · p99 5,930.57 · max 6,000.00 |
| plano_id | numerico | 0.00 | 3 | min 1.00 · p50 2.00 · p99 3.00 · max 3.00 |
| periodicidade | texto | 0.00 | 2 | mensal: 6,538, anual: 406 |
| metodo_pagamento | texto | 0.00 | 3 | cartao: 5,185, pix: 1,116, boleto: 643 |
| status | texto | 0.00 | 4 | encerrada: 3,691, ativa: 3,158, cancelamento_agendado: 61, inadimplente: 34 |
| iniciada_em | data_hora | 0.00 | 6,943 | 2023-10-01 03:12:11 → 2026-11-01 02:44:00 |
| trial_fim_em | data_hora | 94.79 | 362 | 2023-10-09 10:02:38 → 2024-04-07 22:24:41 |
| cancelamento_solicitado_em | data_hora | 63.44 | 2,539 | 2023-10-07 22:40:43 → 2026-11-01 02:57:23 |
| encerrada_em | data_hora | 46.85 | 3,134 | 2023-10-09 22:48:24 → 2026-10-31 23:00:00 |
| tipo_encerramento | texto | 46.85 | 2 | voluntario: 2,478, involuntario: 1,213 |
| renovacao_automatica | flag | 0.00 | 2 | 1: 5,185, 0: 1,759 |
| assinatura_anterior_id | numerico | 86.41 | 944 | min 1.00 · p50 2,151.50 · p99 6,209.97 · max 6,772.00 |

### `assinatura_eventos`

| Coluna | Tipo | Nulos % | Distintos | Resumo |
|---|---|---:|---:|---|
| evento_id | numerico | 0.00 | 25,825 | min 1.00 · p50 12,913.00 · p99 25,566.76 · max 25,825.00 |
| assinatura_id | numerico | 0.00 | 6,943 | min 1.00 · p50 2,693.00 · p99 6,767.76 · max 6,944.00 |
| tipo | texto | 0.00 | 13 | assinatura_criada: 6,942, inadimplencia_iniciada: 4,800, encerrada: 3,691, inadimplencia_resolvida: 3,560, cancelamento_solicitado: 2,538, upgrade: 1,629, reativada: 944, downgrade: 636 |
| ocorrido_em | data_hora | 0.00 | 23,524 | 2023-10-01 03:12:11 → 2026-10-31 23:36:46 |
| plano_anterior_id | numerico | 91.23 | 3 | min 1.00 · p50 2.00 · p99 3.00 · max 3.00 |
| plano_novo_id | numerico | 60.69 | 3 | min 1.00 · p50 2.00 · p99 3.00 · max 3.00 |
| origem | texto | 0.00 | 4 | sistema: 12,636, web: 9,126, app: 3,838, suporte: 225 |

### `faturas`

| Coluna | Tipo | Nulos % | Distintos | Resumo |
|---|---|---:|---:|---|
| fatura_id | numerico | 0.00 | 60,835 | min 1.00 · p50 30,418.00 · p99 60,226.66 · max 60,837.00 |
| assinatura_id | numerico | 0.00 | 6,803 | min 1.00 · p50 2,392.00 · p99 6,506.66 · max 6,944.00 |
| conta_id | numerico | 0.00 | 5,900 | min 1.00 · p50 2,051.00 · p99 5,618.00 · max 5,998.00 |
| preco_id | numerico | 0.00 | 18 | min 1.00 · p50 13.00 · p99 17.00 · max 18.00 |
| cupom_resgate_id | numerico | 92.55 | 2,287 | min 1.00 · p50 1,071.00 · p99 2,241.68 · max 2,289.00 |
| periodo_inicio | data | 0.00 | 1,123 | 2023-10-01 → 2026-10-31 |
| periodo_fim | data | 0.00 | 1,311 | 2023-10-31 → 2027-10-30 |
| emitida_em | data_hora | 0.00 | 60,697 | 2023-10-01 03:15:13 → 2026-10-31 23:34:41 |
| vencimento_em | data | 0.00 | 1,124 | 2023-10-01 → 2026-11-03 |
| valor_bruto | numerico | 0.00 | 18 | min 18.90 · p50 47.90 · p99 209.00 · max 649.00 |
| valor_desconto | numerico | 0.00 | 44 | min 0.00 · p50 0.00 · p99 32.45 · max 239.50 |
| valor_membro_extra | numerico | 0.00 | 3 | min 0.00 · p50 0.00 · p99 13.90 · max 13.90 |
| valor_total | numerico | 0.00 | 66 | min 0.00 · p50 44.90 · p99 209.00 · max 662.90 |
| status | texto | 0.00 | 5 | paga: 59,434, vencida: 1,213, estornada: 85, reembolsada: 61, aberta: 42 |

### `pagamentos`

| Coluna | Tipo | Nulos % | Distintos | Resumo |
|---|---|---:|---:|---|
| pagamento_id | numerico | 0.00 | 66,090 | min 1.00 · p50 33,045.50 · p99 65,429.11 · max 66,090.00 |
| fatura_id | numerico | 0.15 | 60,581 | min 1.00 · p50 30,491.50 · p99 60,190.09 · max 60,835.00 |
| conta_id | numerico | 0.00 | 5,899 | min 1.00 · p50 2,061.00 · p99 5,616.00 · max 5,998.00 |
| metodo | texto | 0.00 | 3 | cartao: 49,957, pix: 10,530, boleto: 5,603 |
| tipo | texto | 0.00 | 3 | cobranca: 65,944, chargeback: 85, reembolso: 61 |
| tentativa | numerico | 0.00 | 4 | min 1.00 · p50 1.00 · p99 4.00 · max 4.00 |
| processado_em | data_hora | 0.00 | 65,989 | 2023-10-01 11:01:35 → 2026-10-31 23:58:22 |
| valor_brl | numerico | 0.00 | 79 | min -64.90 · p50 44.90 · p99 209.00 · max 662.90 · **146 negativos** |
| status | texto | 0.00 | 5 | aprovado: 59,734, recusado: 5,774, expirado: 436, contestado: 85, processado: 61 |
| codigo_recusa | texto | 91.26 | 5 | saldo_insuficiente: 2,423, cartao_expirado: 1,367, nao_autorizado: 1,037, erro_emissor: 580, suspeita_fraude: 367 |

### `titulos`

| Coluna | Tipo | Nulos % | Distintos | Resumo |
|---|---|---:|---:|---|
| titulo_id | numerico | 0.00 | 3,000 | min 1.00 · p50 1,500.50 · p99 2,970.01 · max 3,000.00 |
| tipo | texto | 0.00 | 2 | filme: 2,300, serie: 700 |
| nome | texto | 0.00 | 3,000 | top: O Relógio de Toju (1), Ribeira Lócri: O Relógio (1), Calebe e o Abismo Distan (1) |
| ano_lancamento | numerico | 0.00 | 54 | min 1,960.00 · p50 2,021.00 · p99 2,026.00 · max 2,026.00 |
| duracao_min | numerico | 23.33 | 82 | min 68.00 · p50 104.00 · p99 140.00 · max 152.00 |
| classificacao_indicativa | texto | 0.00 | 6 | 14: 812, 12: 745, 10: 447, 16: 445, L: 436, 18: 115 |
| original | flag | 0.00 | 2 | 0: 2,527, 1: 473 |
| estudio_id | numerico | 0.00 | 45 | min 1.00 · p50 5.00 · p99 43.00 · max 45.00 |
| idioma_original | texto | 0.00 | 6 | en: 1,226, pt: 1,114, es: 255, ja: 156, ko: 155, fr: 94 |
| pais_origem | texto | 0.00 | 14 | BR: 959, US: 484, AU: 270, GB: 239, CA: 233, JP: 156, PT: 155, KR: 155 |
| sinopse | texto | 0.00 | 1,691 | top: Uma estudante tenta prot (7), Uma família inteira se e (6), Uma médica plantonista p (5) |

### `episodios`

| Coluna | Tipo | Nulos % | Distintos | Resumo |
|---|---|---:|---:|---|
| episodio_id | numerico | 0.00 | 24,236 | min 1.00 · p50 12,118.50 · p99 23,993.65 · max 24,236.00 |
| titulo_id | numerico | 0.00 | 700 | min 2.00 · p50 1,461.00 · p99 2,992.00 · max 3,000.00 |
| temporada | numerico | 0.00 | 11 | min 1.00 · p50 2.00 · p99 8.00 · max 11.00 |
| numero | numerico | 0.00 | 26 | min 1.00 · p50 6.00 · p99 22.00 · max 26.00 |
| nome | texto | 0.00 | 89 | top: Episódio 3 (827), Episódio 1 (824), Episódio 2 (818) |
| duracao_min | numerico | 0.00 | 55 | min 11.00 · p50 41.00 · p99 61.00 · max 65.00 |
| disponivel_desde | data_hora | 0.00 | 677 | 2020-01-25 07:00:00 → 2026-10-24 07:00:00 |

### `sessoes_app`

| Coluna | Tipo | Nulos % | Distintos | Resumo |
|---|---|---:|---:|---|
| sessao_id | numerico | 0.00 | 1,046,532 | min 1.00 · p50 524,963.50 · p99 1,038,856.69 · max 1,049,322.00 |
| perfil_id | numerico | 0.00 | 14,627 | min 1.00 · p50 4,691.00 · p99 14,177.00 · max 15,523.00 |
| dispositivo_id | numerico | 0.00 | 13,676 | min 1.00 · p50 4,396.00 · p99 13,477.00 · max 14,741.00 |
| versao_app | texto | 0.00 | 14 | 6.1.0: 196,288, 6.0.0: 139,035, 5.3.0: 116,339, 6.2.0: 106,064, 5.1.0: 102,359, 5.2.0: 94,276, 5.0.0: 86,012, 4.5.0: 56,080 |
| inicio_em | data_hora | 0.00 | 1,035,366 | 2023-10-01 21:26:17 → 2026-11-01 03:49:31 |
| fim_em | data_hora | 0.00 | 1,036,121 | 2023-10-01 23:10:40 → 2026-11-02 01:21:11 |
| ip | texto | 0.00 | 217,728 | top: 10.42.43.220 (1085), 10.41.141.165 (987), 10.40.239.110 (802) |
| regiao | texto | 5.92 | 5 | Sudeste: 413,699, Nordeste: 257,047, Sul: 145,461, Norte: 89,920, Centro-Oeste: 78,396 |

### `reproducoes`

| Coluna | Tipo | Nulos % | Distintos | Resumo |
|---|---|---:|---:|---|
| reproducao_id | numerico | 0.00 | 1,168,273 | min 1.00 · p50 584,137.00 · p99 1,156,590.28 · max 1,168,273.00 |
| perfil_id | numerico | 0.00 | 14,168 | min 1.00 · p50 4,086.00 · p99 14,010.28 · max 15,518.00 |
| sessao_id | numerico | 0.00 | 757,967 | min 1.00 · p50 588,641.00 · p99 1,041,490.28 · max 1,049,322.00 |
| dispositivo_id | numerico | 0.00 | 13,128 | min 1.00 · p50 3,816.00 · p99 13,317.28 · max 14,737.00 |
| titulo_id | numerico | 0.00 | 3,000 | min 1.00 · p50 1,395.00 · p99 2,945.00 · max 3,000.00 |
| episodio_id | numerico | 52.77 | 18,011 | min 1.00 · p50 10,541.00 · p99 23,682.00 · max 24,236.00 |
| inicio_em | data_hora | 0.00 | 1,154,118 | 2023-10-01 21:30:26 → 2026-11-01 23:25:47 |
| fim_em | data_hora | 0.24 | 1,151,572 | 2023-10-01 23:09:34 → 2026-11-02 01:19:51 |
| segundos_assistidos | numerico | 0.00 | 19,039 | min -3,579,000.00 · p50 3,302.00 · p99 7,125,000.00 · max 25,509,000.00 · **559 negativos** |
| percentual_concluido | numerico | 0.00 | 11,944 | min 0.00 · p50 95.07 · p99 100.00 · max 139.98 |
| qualidade_video | texto | 0.93 | 4 | 1080p: 455,132, 720p: 346,391, 4k: 223,486, 480p: 132,353 |
| eventos_buffering | numerico | 0.00 | 15 | min 0.00 · p50 0.00 · p99 3.00 · max 16.00 |
| origem_autoplay | flag | 0.00 | 2 | 0: 1,050,737, 1: 117,536 |
| origem_recomendacao | flag | 0.00 | 2 | 0: 760,711, 1: 407,562 |
| versao_app | texto | 0.00 | 14 | 6.1.0: 255,138, 6.0.0: 165,740, 6.2.0: 140,182, 5.3.0: 129,353, 5.1.0: 104,076, 5.2.0: 99,370, 5.0.0: 81,814, 4.5.0: 53,231 |

## Integridade referencial

| De | Para | Preenchidos | Órfãos | Nulos |
|---|---|---:|---:|---:|
| precos.plano_id | planos.plano_id | 18 | 0 | 2 |
| contas.canal_aquisicao_id | canais.canal_id | 6,000 | 0 | 0 |
| contas.indicada_por_conta_id | contas.conta_id | 532 | 0 | 5,468 |
| perfis.conta_id | contas.conta_id | 15,525 | 0 | 0 |
| dispositivos.conta_id | contas.conta_id | 14,745 | 0 | 0 |
| assinaturas.conta_id | contas.conta_id | 6,944 | 0 | 0 |
| assinaturas.plano_id | planos.plano_id | 6,944 | 0 | 0 |
| assinaturas.assinatura_anterior_id | assinaturas.assinatura_id | 944 | 0 | 6,000 |
| assinatura_eventos.assinatura_id | assinaturas.assinatura_id | 25,825 | 0 | 0 |
| faturas.assinatura_id | assinaturas.assinatura_id | 60,835 | 0 | 0 |
| faturas.preco_id | precos.preco_id | 60,835 | 0 | 0 |
| pagamentos.fatura_id | faturas.fatura_id | 65,992 | 0 | 98 |
| pagamentos.conta_id | contas.conta_id | 66,090 | 0 | 0 |
| episodios.titulo_id | titulos.titulo_id | 24,236 | 0 | 0 |
| sessoes_app.perfil_id | perfis.perfil_id | 1,046,532 | 0 | 0 |
| sessoes_app.dispositivo_id | dispositivos.dispositivo_id | 1,046,532 | 0 | 0 |
| reproducoes.perfil_id | perfis.perfil_id | 1,168,273 | 0 | 0 |
| reproducoes.sessao_id | sessoes_app.sessao_id | 1,168,273 | 2,874 | 0 |
| reproducoes.dispositivo_id | dispositivos.dispositivo_id | 1,168,273 | 0 | 0 |
| reproducoes.titulo_id | titulos.titulo_id | 1,168,273 | 0 | 0 |
| reproducoes.episodio_id | episodios.episodio_id | 551,804 | 0 | 616,469 |

## Sequência de eventos por assinatura

| Transição | Ocorrências |
|---|---:|
| encerrada -> FIM | 3,595 |
| inadimplencia_iniciada -> inadimplencia_resolvida | 3,501 |
| cancelamento_solicitado -> encerrada | 2,381 |
| assinatura_criada -> inadimplencia_iniciada | 1,990 |
| inadimplencia_resolvida -> inadimplencia_iniciada | 1,534 |
| assinatura_criada -> FIM | 1,268 |
| inadimplencia_iniciada -> encerrada | 1,180 |
| assinatura_criada -> cancelamento_solicitado | 1,049 |
| assinatura_criada -> reativada | 944 |
| inadimplencia_resolvida -> FIM | 813 |
| assinatura_criada -> upgrade | 754 |
| upgrade -> FIM | 555 |
| inadimplencia_resolvida -> cancelamento_solicitado | 539 |
| upgrade -> inadimplencia_iniciada | 515 |
| assinatura_criada -> trial_iniciado | 362 |
| inadimplencia_resolvida -> upgrade | 357 |
| reativada -> cancelamento_solicitado | 300 |
| reativada -> inadimplencia_iniciada | 275 |
| assinatura_criada -> downgrade | 231 |
| reativada -> FIM | 228 |
| trial_iniciado -> trial_convertido | 223 |
| downgrade -> inadimplencia_iniciada | 191 |
| upgrade -> cancelamento_solicitado | 189 |
| upgrade -> upgrade | 164 |
| upgrade -> downgrade | 158 |
| cancelamento_solicitado -> FIM | 156 |
| downgrade -> upgrade | 155 |
| inadimplencia_resolvida -> metodo_pagamento_alterado | 145 |
| downgrade -> FIM | 142 |
| trial_iniciado -> cancelamento_solicitado | 139 |
| inadimplencia_resolvida -> downgrade | 130 |
| assinatura_criada -> metodo_pagamento_alterado | 116 |
| metodo_pagamento_alterado -> FIM | 105 |
| encerrada -> cancelamento_solicitado | 96 |
| downgrade -> cancelamento_solicitado | 96 |
| metodo_pagamento_alterado -> inadimplencia_iniciada | 89 |
| inadimplencia_iniciada -> assinatura_criada | 89 |
| assinatura_criada -> membro_extra_adicionado | 88 |
| trial_convertido -> inadimplencia_iniciada | 81 |
| assinatura_criada -> encerrada | 77 |

| Caminho completo | Assinaturas |
|---|---:|
| assinatura_criada | 1,263 |
| assinatura_criada > cancelamento_solicitado > encerrada | 1,018 |
| assinatura_criada > inadimplencia_iniciada > encerrada | 497 |
| assinatura_criada > reativada > cancelamento_solicitado > encerrada | 291 |
| assinatura_criada > inadimplencia_iniciada > inadimplencia_resolvida | 288 |
| assinatura_criada > upgrade | 245 |
| assinatura_criada > inadimplencia_iniciada > inadimplencia_resolvida > cancelamento_solicitado > encerrada | 243 |
| assinatura_criada > reativada | 228 |
| assinatura_criada > inadimplencia_iniciada > inadimplencia_resolvida > inadimplencia_iniciada > encerrada | 151 |
| assinatura_criada > trial_iniciado > cancelamento_solicitado > encerrada | 139 |
| assinatura_criada > upgrade > cancelamento_solicitado > encerrada | 101 |
| assinatura_criada > inadimplencia_iniciada > inadimplencia_resolvida > inadimplencia_iniciada > inadimplencia_resolvida | 99 |

## Imperfeições nativas da base de referência

| Achado | Valor |
|---|---:|
| repro_segundos_negativos | 559 |
| repro_segundos_zero | 4,443 |
| repro_maior_que_conteudo | 250,877 |
| repro_fim_nulo | 2,809 |
| repro_qualidade_nula | 10,911 |
| repro_ordem_1000x_app6_movel | 248,281 |
| repro_ordem_1000x_fora_app6_movel | 0 |
| uf_fora_do_padrao | 194 |
| contas_email_interno | 33 |
| contas_email_qa | 11 |
| faturas_pagas_sem_pagamento | 233 |
| pagamentos_sem_fatura | 98 |
| sessoes_regiao_nula | 62,009 |
| sessoes_ip_interno | 848,334 |
