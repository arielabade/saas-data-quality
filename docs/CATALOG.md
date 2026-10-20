# Catálogo de defeitos

Para cada defeito: como o injetor o cria, como o ETL o detecta, o que faz e por quê. Precisão e recall medidos de cada
detecção estão em [`reports/RESULTADOS.md`](../reports/RESULTADOS.md). Toda regra tem teste positivo e negativo em
[`tests/test_rules.py`](../tests/test_rules.py) ou [`tests/test_state_machine.py`](../tests/test_state_machine.py).

**Ações:** remover · corrigir · limitar · imputar · sinalizar · quarentena · excluir das métricas.

## Assinatura e cobrança

| Defeito | Como é injetado | Detecção | Ação | Por quê |
|---|---|---|---|---|
| **Evento fora de ordem** | 4% das assinaturas com cancelamento/encerramento: o evento é movido para 2–120 dias **antes** da criação | Máquina de estados: evento antes de `assinatura_criada` (`state.machine.fix_event_order`) | **Corrigir** pela data do cabeçalho; sem cabeçalho, **quarentena**. Até 24 h antes: desvio de relógio, corrigido para a criação | Cancelar antes de assinar é impossível. O cabeçalho é a fonte independente que confirma a data. Sem correção, a conta nunca churna |
| **Transição inválida** (nativo) | — (ex.: evento depois de `encerrada`) | Par (estado, evento) fora de `TRANSITIONS` | **Sinalizar**, ignorar o evento | Uma assinatura encerrada não muda de estado; quem volta é uma assinatura nova |
| **Assinaturas sobrepostas** | 2% das contas ativas recebem uma segunda assinatura (outro plano) sem encerrar a primeira, com faturas e pagamentos | Intervalos vigentes por conta (`resolve_overlaps`): a mais nova começa dentro de outra e não tem `assinatura_anterior_id` | **Quarentena** da assinatura nova com faturas e pagamentos; aviso ao financeiro | É duplicata de cadastro, não troca de plano. Se for cobrança real em dobro, o caminho é reembolso, não MRR |
| **Webhook duplicado** | 3% das cobranças aprovadas reentregues 1–180 s depois, com id novo | Chave idempotente (fatura, tipo, tentativa, status, valor) e janela de 1 h | **Remover** as reentregas; fica a primeira | O dinheiro entrou uma vez. Sem isso, o MRR (calculado em caixa) soma duas vezes |
| **Retentativa duplicada** | 5% das recusas registradas de novo, 1–900 s depois, como pagamento separado | Mesma chave e janela | **Remover** | Infla "falhas de pagamento", a feature mais preditiva de churn involuntário. A retentativa real tem outro nº de tentativa e dias de distância |
| **Preço diferente do vigente** | 1,2% das faturas emitidas com o preço da tabela **anterior** (e o pagamento com o mesmo valor) | SCD2 (`state.scd`): o preço vigente para plano, periodicidade e data do período ≠ o preço da fatura | **Corrigir** fatura e pagamento para o preço vigente | O contrato é a tabela vigente na data; cache de preço vencido é bug de faturamento ([D17](DECISIONS.md)) |
| **Pagamento órfão** | 0,2% de pagamentos apontando para fatura inexistente | Integridade referencial | **Quarentena** | Sem fatura não há a qual assinatura ele pertence; entra só depois de reconciliado |

## Uso

| Defeito | Como é injetado | Detecção | Ação | Por quê |
|---|---|---|---|---|
| **Sessão absurda** (player aberto a noite toda) | 0,2% das reproduções com 10–30 h; a sessão acompanha | Regra física: assistido > 105% da duração do conteúdo; sessão termina > 2 h depois da última reprodução | **Limitar** à duração; **corrigir** o fim da sessão | Quem deixou o player aberto assistiu no máximo o conteúdo inteiro |
| **Tempo negativo** | 0,15% das reproduções | Regra física | **Corrigir** com fim − início (limitado à duração); sem horários válidos, zera e **sinaliza** | Remover perderia a informação de que houve reprodução |
| **Tempo maior que o conteúdo** | 0,3% com 1,5 a 8 vezes a duração | Regra física | **Limitar** à duração | Idem |
| **Mais de 24 h por aparelho no dia** (nativo) | — (vários perfis no mesmo aparelho ao mesmo tempo) | Soma por aparelho e dia > 24 h | **Limitar** proporcionalmente | Um aparelho físico não toca mais de 24 h num dia |
| **Replay de lote** | 3 dias × 6 h de sessões e reproduções reinseridas com ids novos, 20–40 h depois | Chave natural (perfil, aparelho, título, episódio, início) | **Remover** as cópias; fica a de chegada mais antiga | O mesmo fato não acontece duas vezes no mesmo segundo |
| **Fuso misturado** | O web grava hora local **sem offset** entre fev e ago/2025 | Contrato de formato: o web sempre manda offset | **Corrigir**: hora local da conta → UTC | O formato denuncia o erro com 100% de certeza; estatística não precisa entrar |
| **Relógio errado do aparelho** | 1,2% dos aparelhos com relógio deslocado (±1 h, ±2–12 h, ±1–40 dias) ou zerado (ano 2000) | Mediana por aparelho de (recebido no servidor − fim) acima de 30 min, consistente; ano < 2023 | **Corrigir** pelo desvio do aparelho; zerado: reconstruir pela hora do servidor | O servidor é o relógio confiável. A correção é por aparelho, para não confundir com atraso offline |
| **Evento atrasado** (sincronização offline) | 3% das sessões móveis chegam 1–20 dias depois | Recebido − ocorrido > 6 h numa linha isolada | **Sinalizar**; a carga reprocessa o mês do evento (janela de 30 dias); fora da janela, **quarentena** | O horário está certo, só a chegada atrasou. Descartar subestima os meses recentes |
| **Troca de ID do mesmo aparelho** | 4% dos aparelhos ganham um id novo (reinstalação) a partir de uma data | Mesma conta, tipo e plataforma; o novo id começa depois do último uso do antigo, dentro do p99 do intervalo entre sessões de um aparelho (≈40 dias, medido nos dados); nenhum uso simultâneo | **Corrigir**: unificar no id original | Infla "nº de aparelhos" (feature de churn e de compartilhamento) e quebra o limite de 24 h por aparelho |
| **Sessão/reprodução órfã** | 0,1% das sessões (com suas reproduções) de perfil inexistente | Integridade referencial | **Quarentena** | Sem perfil não há conta, assinatura nem fuso |
| **Reprodução sem sessão** (nativo) | — | Chave lógica | **Sinalizar** | Perfil e aparelho existem; a sessão se perdeu na ingestão ([D21](DECISIONS.md)) |

## Cadastro

| Defeito | Como é injetado | Detecção | Ação | Por quê |
|---|---|---|---|---|
| **Contas internas e de QA** | 40 clones de clientes com 1 a 4 sinais: e-mail de teste, nome "Teste", CPF inválido, rede de QA. Sem sinal de CPF, o CPF fica **duplicado** | Regras de cadastro: domínio interno, padrão de e-mail e de nome, dígito do CPF, CPF repetido (a conta mais nova é a cópia), mais de 50% das sessões na rede `10.250.x` | **Excluir das métricas** (a conta fica na camada clean) | O financeiro precisa reconciliar; as métricas, não. Qualquer sinal basta: incluir teste custa mais que excluir um raro "João Teste" |
| **UF nula só em cadastro pela TV** | 70% das contas cujo primeiro aparelho é TV perdem a UF | Teste do mecanismo: qui-quadrado e V de Cramér contra canal, primeiro aparelho e plano → **MAR** (depende do aparelho) | **Imputar a região** pela moda das sessões da conta; a UF fica nula | Imputar pela moda geral (Sudeste) enviesaria justo o grupo da TV. A região vem de dado observado da própria conta |
| **Texto fora do padrão** (nativo) | — (`Smart TV`, `sp`, `Bahia`) | Staging | **Corrigir** para a forma canônica | Formato, não julgamento |
| **Milissegundos no app 6.x móvel** (nativo) | — | Staging (versão do app × tipo de aparelho) | **Corrigir** a unidade (÷ 1.000) | Formato conhecido; sem isso, o engajamento móvel de 2026 sai mil vezes maior |

## Padrões anômalos por conta (Isolation Forest)

| Padrão | Como é injetado | Detecção | Ação | Por quê |
|---|---|---|---|---|
| **Robô** | 15 clones com cerca de 60 reproduções de 30–120 s por dia, a qualquer hora, num aparelho web | Isolation Forest por conta-mês com explicação "robô" (mais de 60% de reproduções curtas e mais de 15 por dia) | **Excluir das métricas** | Não é gente assistindo: infla engajamento e distorce recomendação |
| **Compartilhamento acima do limite** (anomalia real) | 30 contas com (telas do plano + 1) aparelhos de outras regiões tocando ao mesmo tempo | Isolation Forest com explicação "telas acima do limite" (máximo de simultâneas > plano e mais de 2 regiões) | **Sinalizar** para o time comercial (membro extra) | O uso é real e a receita também; remover tiraria engajamento verdadeiro |

## Outliers verdadeiros (não podem cair)

| Caso | Como é injetado | O que deveria acontecer |
|---|---|---|
| **Maratona na estreia** | 250 perfis assistem 6–12 episódios de uma temporada original nos 3 dias após a estreia | O modelo sazonal explica o pico pela estreia; IQR e z-score marcam, mas só para sinalizar |
| **Usuários muito intensos** | 25 perfis com 8–14 h/dia por 20 dias na TV | Passam na regra física (menos de 24 h); estatística sinaliza |
| **Pico de feriado** | +35% de reproduções em 24, 25 e 31/12 e 01/01 | Explicado pelo calendário |
| **Compartilhamento pago dentro do limite** | 30 contas Padrão/Premium com membro extra num aparelho de outra região | Não é marcado como acima do limite |
