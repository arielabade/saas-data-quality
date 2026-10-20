# A base fonte: o que ela é e o que o perfil encontrou

A fonte é uma base sintética de um serviço de streaming por assinatura brasileiro e fictício
(outubro de 2023 a outubro de 2026), gerada pelo repositório
[`dados-sinteticos-streaming-cinelume`](https://github.com/arielabade/dados-sinteticos-streaming-cinelume).
Este projeto a trata como **somente leitura**. O gerador roda com a saída e o gabarito apontados para fora da
pasta original. O gabarito é apagado em seguida e não é usado em nenhuma etapa.

O perfil completo, tabela a tabela e coluna a coluna, é gerado em [`reports/profile/PROFILE.md`](../reports/profile/PROFILE.md)
por `python -m dq.profile.profiler`. Este documento conta o que o perfil mostra e o que muda no pipeline por causa disso.

## Como os dados chegam aqui

```
gerar_dados.py (escala small, semente 20231001)  ->  data/generated/{csv,parquet}
docker compose (MySQL 8.4, schema.sql da fonte)   ->  carga das 14 tabelas do escopo
dq.extract.extract                                ->  data/source/*.parquet  (a base de referência)
```

Das 29 tabelas da fonte, 14 entram no escopo: as que alimentam assinatura, cobrança, MRR, churn e engajamento.
Ficaram fora os eventos de interface (5,2 milhões de linhas), os heartbeats do player (2,7 milhões, só de 5% dos perfis),
marketing, NPS e atendimento. Nenhuma métrica deste projeto depende delas, e incluí-las não caberia no disco disponível
(ver [DECISIONS.md](DECISIONS.md)).

| Tabela | Linhas | Grão | Chave |
|---|---:|---|---|
| `contas` | 6.000 | titular da conta | `conta_id` |
| `perfis` | 15.525 | perfil (até 5 por conta) | `perfil_id` |
| `dispositivos` | 14.745 | aparelho registrado | `dispositivo_id` |
| `planos` / `precos` | 3 / 20 | plano; versão de preço com vigência | `plano_id` / `preco_id` |
| `assinaturas` | 6.944 | período contínuo de assinatura | `assinatura_id` |
| `assinatura_eventos` | 25.825 | evento da assinatura | `evento_id` |
| `faturas` | 60.835 | ciclo de cobrança | `fatura_id` |
| `pagamentos` | 66.090 | tentativa de cobrança, reembolso ou contestação | `pagamento_id` |
| `titulos` / `episodios` | 3.000 / 24.236 | catálogo | `titulo_id` / `episodio_id` |
| `sessoes_app` | 1.046.532 | abertura do app | `sessao_id` |
| `reproducoes` | 1.168.273 | reprodução de um título/episódio | `reproducao_id` |

Nenhuma chave primária duplicada. Todas as chaves estrangeiras declaradas batem. A única ligação quebrada é lógica:
**2.874 reproduções apontam para sessões que não existem**, porque as sessões se perderam em falhas do pipeline de ingestão
da própria fonte. Por isso o ETL não põe essas reproduções em quarentena: o perfil e o aparelho existem.

## Tipos, nulos e distribuições que importam

- **Datas e horas** estão em UTC, com precisão de segundos. Colunas `DATE` são dias civis de Brasília.
- **Dinheiro** vem em `DECIMAL(10,2)` BRL. O pipeline converte para centavos inteiros e grava a moeda explicitamente.
- **Nulos esperados pelo desenho:**
  - `assinaturas.encerrada_em` (46,8%): assinatura ainda vigente;
  - `assinatura_anterior_id` (86,4%): só reativações têm;
  - `titulos.duracao_min` (23,3%): séries, cuja duração está no episódio;
  - `reproducoes.episodio_id` (52,8%): filmes.
- **Nulos de cadastro:** `telefone` 7,7%, `data_nascimento` 11,9% e `cep` 5,2%. Os três são compatíveis com MCAR,
  sem dependência de canal, aparelho ou plano (teste qui-quadrado com V de Cramér).
- **Valores monetários:**
  - fatura mediana de R$ 44,90, entre R$ 0 (cupom de 100%) e R$ 662,90 (anual Premium);
  - 146 pagamentos negativos, todos reembolsos ou contestações, o que é correto pelo desenho.
- **Tempo assistido** (`segundos_assistidos`):
  - mediana de 3.302 s, mas máximo de 25,5 milhões de segundos e mínimo de -3,58 milhões;
  - a cauda é quase toda uma questão de unidade (abaixo).
- **Horas por perfil-dia:**
  - mediana de 1,5 h, p99 de 30 h e assimetria de 11, com a unidade ainda sem correção;
  - quase tudo concentrado em poucas horas, com uma cauda enorme;
  - é por isso que escala importa ([TECHNIQUES.md](TECHNIQUES.md#escalas)).

## Imperfeições nativas (antes de qualquer defeito injetado)

A fonte avisa que contém imperfeições propositais e não documentadas. O perfil encontrou estas, e cada uma virou regra:

| Achado | Tamanho | O que o pipeline faz |
|---|---:|---|
| App 6.x em celular e tablet grava `segundos_assistidos` em **milissegundos** | 248.281 reproduções (21%) | Staging divide por 1.000 (é formato, não erro). |
| Tipo de dispositivo com variações (`Smart TV`, `smartphone`, `WEB`, `tablet `…) | 363 aparelhos | Staging normaliza para tv, celular, web e tablet. |
| UF fora do padrão (`sp`, `Bahia`, `" RJ"`) | 194 contas | Staging normaliza para a sigla. |
| Vários perfis tocando ao mesmo tempo **no mesmo aparelho** (uma TV com 100 h num dia) | ~3 mil aparelho-dia acima de 24 h | Regra física: até 24 h por aparelho no dia. |
| Tempo negativo / zero / maior que o conteúdo (fora a questão da unidade) | 559 / 4.443 / ~2,6 mil | Regras físicas (corrigir ou limitar). |
| Eventos de assinatura alguns **minutos antes** de `assinatura_criada` (relógios de sistemas diferentes) | 115 eventos | Tolerância de 24 h: corrige para a criação. |
| Reativação começando antes do fim da anterior | 5 assinaturas | Mantida: tem vínculo `assinatura_anterior_id`. |
| Contas de funcionários (`@cinelume.example`) e de QA (`qa+…`, rede `10.250.x`) | 33 + 11 contas | Saem das métricas. |
| Robôs (rede `203.0.113.x`, dezenas de reproduções curtas por dia) | ~12 contas | Isolation Forest com explicação; saem do engajamento. |
| Fatura paga sem nenhum pagamento | 233 faturas | O MRR usa o valor da fatura nesses casos. |
| Pagamento sem fatura (`fatura_id` nulo) | 98 pagamentos | Mantido e sinalizado; não entra no MRR. |
| Quedas de volume em dias de falha do pipeline | ~24 dias | O modelo sazonal marca como "perda de dados provável". |

Como a base de referência já tem tudo isso, a avaliação roda as mesmas técnicas nela. **O que uma técnica marca também na
referência é "nativo" e não conta como falso positivo** ([TECHNIQUES.md](TECHNIQUES.md#como-medir)).

## Sequência de eventos por assinante

Cada assinatura é um período contínuo; uma reativação cria uma **assinatura nova** ligada à anterior. Os caminhos mais comuns:

| Caminho | Assinaturas |
|---|---:|
| criada (ainda vigente) | 1.263 |
| criada → cancelamento solicitado → encerrada | 1.018 |
| criada → inadimplência → encerrada | 497 |
| criada → reativada → cancelamento solicitado → encerrada | 291 |
| criada → inadimplência → inadimplência resolvida | 288 |
| criada → upgrade | 245 |

### Como churn, reativação e mudança de plano aparecem

- **Churn voluntário:** `cancelamento_solicitado`. O acesso segue até o fim do ciclo pago, depois vem `encerrada` com
  `tipo_encerramento = voluntario` (2.478 assinaturas). Entre os dois eventos o estado é **cancelamento agendado**: a
  conta ainda é pagante.
- **Churn involuntário:** `inadimplencia_iniciada` (cartão recusado, com retentativas em D+1, D+3 e D+7, ou Pix/boleto vencido)
  seguido de `encerrada` com `tipo_encerramento = involuntario` (1.213 assinaturas). Enquanto está inadimplente, a conta está
  em **carência de pagamento**: não é churn ainda.
- **Reativação:** nova linha em `assinaturas` com `assinatura_anterior_id` (944 reativações). O intervalo entre o fim da
  anterior e a volta tem mediana de 50 dias (p10 de 9 dias). Daí a carência de 7 dias na definição de churn
  ([METRICS.md](METRICS.md)).
- **Mudança de plano:** evento `upgrade` (1.629) ou `downgrade` (636) com `plano_anterior_id` e `plano_novo_id`. O
  `assinaturas.plano_id` é o plano **final**, então o plano em cada data só se reconstrói pelos eventos.
- **Preço:** a fatura aponta para `precos.preco_id`. Os reajustes de 01/08/2024 e 01/09/2025 criam novas versões
  (SCD tipo 2 em `dim_preco`).
- **Contas com várias assinaturas:** 5.200 contas têm 1 assinatura, 676 têm 2 e 124 têm 3 ou mais.
- **Foto final:** `assinaturas.status` é uma foto em 31/10/2026: 3.158 ativas, 3.691 encerradas, 61 com cancelamento
  agendado e 34 inadimplentes. Por ser foto, não serve para medir nada mês a mês, e é por isso que o pipeline
  reconstrói a linha do tempo pelos eventos ([ARCHITECTURE.md](ARCHITECTURE.md#máquina-de-estados-da-assinatura)).
