# Definições das métricas

As definições abaixo são as que o código implementa, em `src/dq/load/marts.py` e `src/dq/state/churn.py`. Todas usam a
mesma linha do tempo de estados ([ARCHITECTURE.md](ARCHITECTURE.md#máquina-de-estados-da-assinatura)) e excluem as contas
internas, de teste e os robôs.

Notação: *M* é um mês; *início(M)* = 1º dia às 00:00:00 UTC; *fim(M)* = último dia às 23:59:59 UTC.

## Estados

| Estado | Vigente? | Pagante? |
|---|:-:|:-:|
| trial | sim | não |
| ativo | sim | sim |
| inadimplente | sim (carência de pagamento) | não |
| cancelamento agendado | sim (acesso até o fim do ciclo pago) | sim |
| cancelado | não | não |

## Assinante ativo

**Conta com pelo menos uma assinatura vigente no instante fim(M).** A contagem é por conta, não por assinatura: duas
assinaturas da mesma conta contam uma vez.

## MRR (receita recorrente mensal)

```
MRR(M) = Σ  caixa(f) / meses(f)
         a ∈ assinaturas em estado pagante em fim(M)
         f = fatura de a cujo período cobre o dia de fim(M)
```

- `caixa(f)` é o valor **efetivamente recebido** pela fatura, em centavos: cobranças aprovadas mais reembolsos
  (que são negativos).
- Fatura com status `paga` e nenhum pagamento registrado, uma imperfeição nativa, usa o total da fatura.
- `meses(f)` é 12 para fatura anual e 1 para mensal.
- Assinatura **inadimplente** não entra no MRR; ela é reportada à parte como **MRR em risco**.
- Trial não tem fatura, então contribui zero.
- **Receita por plano** é o mesmo MRR quebrado pelo plano do intervalo vigente em fim(M), reconstruído pelos eventos de
  upgrade e downgrade, e não pelo plano final da assinatura.

Por que caixa e não preço de tabela: é o número que o financeiro reconcilia com o gateway. O efeito colateral é que
**pagamento duplicado infla o MRR**. Por isso a deduplicação de pagamentos vem antes de qualquer soma.

## Churn

Uma conta tem **períodos vigentes**: a união dos intervalos em que alguma assinatura sua estava vigente. Dois períodos
separados por **até 7 dias** viram um só (carência de reativação: troca de cartão, pausa curta).

- **Evento de churn:** fim de um período vigente antes do fim da base (31/10/2026).
- **Tipo:**
  - **voluntário**, se o último estado era cancelamento agendado;
  - **involuntário**, se era inadimplente (falha de pagamento depois das retentativas, ou Pix/boleto não pago);
  - **outro**, nos demais casos.
- **Inadimplência não é churn:** é a carência de pagamento. Só vira churn se terminar em encerramento.

```
taxa_churn(M) = contas com período vigente iniciado antes de início(M) e encerrado dentro de M
                ──────────────────────────────────────────────────────────────────────────────
                contas vigentes em início(M)
```

## Retenção por coorte

- **Coorte:** mês do primeiro período vigente da conta.
- **Retenção:** retenção(c, k) = fração da coorte *c* vigente em fim(c + k).
- **Média de k:** a média ponderada pela base, só entre as coortes que já completaram *k* meses.

## Engajamento

```
horas_por_assinante(M) = horas assistidas em M pelas contas vigentes em fim(M)
                         ─────────────────────────────────────────────────────
                         nº de contas vigentes em fim(M)
```

As horas vêm da camada clean: unidade corrigida, limites físicos aplicados, duplicatas removidas e aparelhos
unificados. O dia de comportamento (perfil-dia) usa o **fuso da conta**; o armazenamento continua em UTC.

## Como cada defeito altera estas métricas

| Defeito | MRR | Assinantes ativos | Churn | Engajamento |
|---|---|---|---|---|
| Webhook e retentativa duplicados | **infla** (caixa somado duas vezes) | — | infla falhas de pagamento (feature) | — |
| Assinatura sobreposta | **infla** (duas faturas pagas no mesmo mês) | — (contagem por conta) | — | — |
| Preço de tabela antiga | **reduz** (preço antigo é menor) | — | — | — |
| Evento fora de ordem | — | infla (a conta nunca churna) | **reduz** (encerramento perdido) | — |
| Contas de teste | infla | infla | dilui | distorce |
| Robôs | — | — | — | **infla** horas |
| Sessão absurda, tempo maior que o conteúdo | — | — | — | **infla** |
| Replay de lote | — | — | — | infla os dias do replay |
| Fuso e relógio errados | — | — | — | joga horas para o dia ou mês errado |
| Atrasado descartado | — | — | — | **reduz** os meses recentes |
| Tratar outlier legítimo como erro | — | — | — | **reduz** (maratonas e usuários intensos somem) |

Os tamanhos de cada efeito estão em [`reports/RESULTADOS.md`](../reports/RESULTADOS.md).
