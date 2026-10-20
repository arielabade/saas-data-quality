# Guia das técnicas

Cada técnica tem duas leituras: **para quem decide** (o que ela responde e quando confiar nela) e **para quem implementa**
(a fórmula e o parâmetro usado aqui). Os resultados medidos estão em [`reports/RESULTADOS.md`](../reports/RESULTADOS.md).

## Como medir

Toda técnica foi rodada na base suja e comparada com o registro de defeitos.

- **Precisão:** dos itens que a técnica marcou, quantos eram defeito.
  `precisão = acertos / (acertos + falsos positivos + legítimos derrubados)`
- **Recall:** dos defeitos que ela deveria pegar, quantos pegou.
  `recall = acertos / defeitos-alvo`
- **Legítimo derrubado:** cliente real tratado como erro (maratona, usuário intenso, feriado, compartilhamento pago).
  Conta contra a técnica.
- **Nativo:** algo que a técnica também marca na base de referência. É um achado real da base, não um erro da técnica,
  e fica fora da precisão.

---

## Detecção de outliers

### IQR (amplitude interquartil)

**Para quem decide.** Pergunta "este número é raro comparado aos outros do mês?". É simples e explicável, mas não sabe se
o raro é bom ou ruim: um cliente apaixonado e um player esquecido aberto parecem iguais.

**Para quem implementa.** Na unidade perfil-dia (horas no dia local), por mês:

```
Q1, Q3 = quantis 25% e 75% das horas do mês
IQR    = Q3 − Q1
outlier se  horas > Q3 + k · IQR,  com k = 3
```

O mês é a referência porque o uso cresce ao longo do tempo. Em distribuições muito assimétricas, como tempo assistido,
mesmo k = 3 corta a cauda real.

### Z-score robusto (mediana e MAD)

**Para quem decide.** É a mesma pergunta do IQR, mas mede a distância até a mediana numa régua que não é puxada pelos
próprios outliers. Costuma marcar mais coisa que o IQR em dados com cauda longa.

**Para quem implementa.**

```
MAD = mediana(|x − mediana(x)|)
z   = 0,6745 · (x − mediana(x)) / MAD
outlier se z > 3,5
```

0,6745 torna o MAD comparável ao desvio-padrão numa normal (Iglewicz e Hoaglin).

### Regra física

**Para quem decide.** Pergunta "isto é possível?". Não depende da distribuição. É a única técnica que pode **mudar**
números, porque o erro é certo: ninguém assiste 30 horas de um episódio de 45 minutos.

**Para quem implementa.**

```
assistido < 0                                → corrigir (fim − início, limitado à duração)
assistido > 1,05 × duração do conteúdo       → limitar à duração
Σ assistido por (aparelho, dia) > 24 h       → reduzir proporcionalmente
sessão.fim > última reprodução.fim + 2 h     → fim = última reprodução + 10 min
```

### Detecção sazonal em séries diárias

**Para quem decide.** Olha o **dia da plataforma**, não o cliente, e pergunta "este dia fugiu do esperado para a época?".
Antes de chamar um pico de erro, procura uma explicação no calendário: estreia de temporada ou feriado. É o que separa
"lançamos uma série" de "o pipeline reprocessou um lote".

**Para quem implementa.** Sobre o total diário de horas `y_t`, em log:

```
ℓ_t     = log(1 + y_t)
T_t     = mediana móvel centrada de ℓ (28 dias)          tendência
S_d     = mediana de (ℓ_t − T_t) por dia da semana d     sazonalidade semanal
r_t     = ℓ_t − T_t − S_d(t)                             resíduo
z_t     = z robusto de r_t;   anômalo se |z_t| > 4
explicação:  feriado?  →  evento real
             temporada lançada em t−3..t com ≥ 5% das reproduções do dia?  →  estreia (evento real)
             z < 0  →  queda (perda de dados provável)
             senão  →  erro provável
```

A comparação usada é o z-score robusto sobre o total diário cru: sem tendência, ele marca o crescimento natural da base e
todo fim de semana forte.

### Isolation Forest em padrões de uso por usuário

**Para quem decide.** Em vez de olhar um número, olha o **jeito** de usar a conta: horários, telas ao mesmo tempo,
regiões, reproduções curtas. Acha padrões que nenhuma regra isolada pega, mas sozinho só diz "é diferente", não "é
errado". Por isso cada anomalia passa por uma explicação, e só "robô" sai das métricas.

**Para quem implementa.** Uma linha por conta-mês, com estas features:

- reproduções e horas por dia ativo;
- fração de reproduções curtas (até 3 min);
- fração na madrugada;
- entropia da hora do dia;
- aparelhos;
- regiões;
- máximo de telas simultâneas (varredura de eventos +1/−1);
- telas acima do limite do plano.

Transformação `log1p`, escala robusta, `IsolationForest(n_estimators=300, contamination=1%)`. O escore de anomalia é
proporcional a 2^(−E[h(x)]/c(n)), em que *h* é a profundidade média até isolar o ponto: pontos raros se isolam em poucos
cortes.

- **Explicação "robô":** reproduções curtas acima de 60% **e** mais de 15 reproduções por dia.
- **Explicação "compartilhamento acima do limite":** telas acima do limite **e** 2 regiões ou mais.

---

## Sequência e estado

### Máquina de estados

**Para quem decide.** O status da assinatura no banco é uma foto de hoje; ele não diz quem estava ativo em março. A
linha do tempo é reconstruída a partir dos eventos, e uma tabela explícita diz quais transições existem. Assim, um evento
impossível, como cancelar antes de assinar, aparece e é tratado, em vez de virar silenciosamente "nunca cancelou".

**Para quem implementa.** Ordena os eventos por (instante, prioridade, id) e aplica `estado ← TRANSITIONS[(estado,
evento)]`. Um par ausente é transição inválida: o evento é ignorado e sinalizado. As regras de tolerância, de cabeçalho e
de quarentena estão em [ARCHITECTURE.md](ARCHITECTURE.md#máquina-de-estados-da-assinatura).

### SCD tipo 2 de preços

**Para quem decide.** O preço do plano muda (reajustes em ago/2024 e set/2025). Cada versão do preço fica guardada com
a data em que valia, e toda cobrança é conferida contra o preço **daquela data**, não contra o preço de hoje.

**Para quem implementa.** `dim_preco(preco_id, plano, periodicidade, versao, valido_de, valido_ate, atual)`, com
`valido_ate` exclusivo vindo da próxima versão. A busca é `valido_de ≤ data < valido_ate`.

### Deduplicação por chave idempotente e janela

**Para quem decide.** O gateway de pagamento reenvia o mesmo aviso quando não recebe confirmação. Duas linhas iguais em
segundos não são duas vendas.

**Para quem implementa.** A chave é (fatura, tipo, tentativa, status, valor). Ordenado por chave e horário, uma linha é
duplicata se a anterior tem a mesma chave e está a até 3.600 s. No uso, a chave natural é (perfil, aparelho, título,
episódio, início) e fica a primeira linha recebida.

### Definição de churn

Ver [METRICS.md](METRICS.md#churn): voluntário, involuntário, carência de pagamento e carência de reativação de 7 dias.

---

## Tratamento: quando remover, corrigir, limitar, imputar ou sinalizar

| Situação | Ação | Critério |
|---|---|---|
| O fato não existiu (duplicata, teste, robô, órfão) | remover / excluir das métricas / quarentena | Existe uma prova independente: chave idempotente, cadastro, padrão explicado, integridade |
| O fato existiu, com o valor errado e uma fonte confiável para o certo | corrigir | Cabeçalho, hora do servidor, SCD, contrato de formato |
| O fato existiu, com o valor impossível e sem fonte do certo | limitar | Limite físico (duração, 24 h) |
| O valor falta e o mecanismo é conhecido | imputar | Só quando há informação observada da própria entidade (região pela sessão) |
| O valor é raro mas possível | sinalizar | Outlier estatístico, compartilhamento, atraso |

### Nulos: mecanismo antes de imputar

- **MCAR** (falta ao acaso): a ausência não depende de nada. Imputar ou não muda pouco a média.
- **MAR** (depende de algo observado): a UF falta mais em quem se cadastrou pela TV. Imputar pela moda geral enviesa
  justamente esse grupo.
- **MNAR** (depende do próprio valor ausente) não é testável com os dados disponíveis.

**Teste usado:** para cada coluna, qui-quadrado entre "é nulo" e cada variável observada (canal, primeiro aparelho, plano),
com o tamanho do efeito pelo V de Cramér:

```
V = sqrt( χ² / (n · (min(linhas, colunas) − 1)) )
MAR se V ≥ 0,1 e p < 0,001
```

---

## Padronização e normalização

- **Datas:** armazenadas em UTC. A análise de comportamento (dia do perfil, madrugada) usa o fuso da conta, que vem da UF
  ou, sem UF, do padrão do país.
- **Valores:** centavos inteiros (`round(valor × 100)`) com `moeda = 'BRL'` explícita. Somar centavos inteiros não
  acumula erro de ponto flutuante.

### Escalas

**Para quem decide.** Tempo assistido é muito assimétrico: a maioria assiste pouco e alguns assistem muito. Quase todo
modelo enxerga distâncias, e a escala decide se essas poucas pessoas dominam a conta.

**Para quem implementa.**

| Escala | Fórmula | Efeito em dado assimétrico |
|---|---|---|
| Min-max | (x − mín) / (máx − mín) | Mantém a forma; a cauda espreme quase tudo perto de 0 |
| Z-score | (x − média) / desvio | Mantém a forma; média e desvio puxados pela cauda |
| Robusta | (x − mediana) / IQR | Centra bem, mas a cauda continua lá |
| Log | log(1 + x) | Comprime a cauda; interpretável (variação relativa) |
| Yeo-Johnson | potência com λ estimado por máxima verossimilhança; aceita 0 e negativos | Aproxima a simetria |

A assimetria e o percentual de pontos espremidos no primeiro décimo da faixa, em cada escala, estão em `RESULTADOS.md`.
A escolha aqui é `log1p` para features de modelo (é o que o modelo de churn usa) e escala robusta só depois do log.
