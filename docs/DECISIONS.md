# Decisões

Cada decisão tem o que foi escolhido, as alternativas descartadas e o motivo. Quando havia duas opções razoáveis, ficou a
recomendada, sem parar o trabalho.

## Fonte e ambiente

**D1. A fonte fica intocada; o gerador escreve fora dela.**
- Escolha: `gerar_dados.py` roda com `-B` (sem `__pycache__`), com `--saida data/generated` e com `--gabarito` numa
  pasta temporária que é apagada logo depois. O MySQL usa um `docker-compose.yml` deste repositório, que monta o
  `schema.sql` da fonte só para leitura.
- Descartado: rodar `docker compose` e o gerador dentro da pasta da fonte, que escrevem `dados/` e `_gabarito/` lá dentro.
- Motivo: a pasta é só leitura, e o gabarito não pode ser usado em nenhuma etapa.

**D2. A pasta fonte vem de `DQ_SOURCE_DIR`.**
- Escolha: o padrão é `../../streaming`, que é onde a base está nesta máquina.
- Contexto: o pedido falava em `../saas/streaming`, mas essa pasta está vazia.
- Motivo: no CI a fonte é clonada do repositório público, e a variável é o que permite isso.

**D3. Escala `small` (≈6 mil contas, 1,2 milhão de reproduções) e 14 das 29 tabelas.**
- Descartado: a escala `medium` (1,7 GB, cinco vezes mais linhas).
- Motivo: a máquina tinha 14 GB livres em disco e cerca de 4 GB de RAM. Cada execução do ETL usa cerca de 2,8 GB, e a
  avaliação roda 15 variantes. As tabelas que ficaram de fora (eventos de interface, heartbeats, marketing, NPS e
  atendimento) não alimentam MRR, churn nem engajamento.

**D4. pandas < 3 e pyarrow < 19.**
- Motivo: com pandas 3.0.6 e pyarrow 26, ler várias tabelas no mesmo processo terminava em `SIGABRT` na saída do
  interpretador. pandas 2.2.3 com pyarrow 18.1 é estável.

**D5. Credenciais.**
- Escolha: `make env` cria o `.env` (fora do git) com uma senha aleatória. O código lê `MYSQL_PASSWORD` do ambiente
  na hora de conectar.
- Motivo: nenhuma senha aparece em código, YAML ou compose.

## Como medir

**D6. A "verdade" é a base de referência passando pelo MESMO pipeline.**
- Contexto: o perfil mostrou que a base "limpa" já tem imperfeições
  ([DATA_SOURCE.md](DATA_SOURCE.md#imperfeições-nativas-antes-de-qualquer-defeito-injetado)).
- Escolha: comparar a variante suja com a referência processada do mesmo jeito. Assim, a diferença entre as duas é
  só o efeito dos defeitos injetados e da limpeza deles.
- Descartado: usar a base de referência crua como verdade. Isso misturaria o efeito dos defeitos com o das imperfeições
  nativas.

**D7. Achado nativo não é falso positivo.**
- Escolha: o que uma técnica marca também quando roda na referência é contado como "nativo" e fica fora do denominador
  da precisão.
- Motivo: é um achado real da base, não um erro da técnica.

**D8. Outlier legítimo derrubado conta como erro na precisão.**
- Descartado: tratá-lo como acerto ("era mesmo um outlier").
- Motivo: para o negócio, derrubar uma maratona de estreia é tão ruim quanto deixar passar um defeito.

**D9. Outliers legítimos e anomalias reais entram na referência.**
- O que entra: maratona de estreia, usuários intensos, pico de feriado, compartilhamento pago e compartilhamento acima
  do limite.
- Motivo: são uso real. O compartilhamento acima do limite fica registrado como "anomalia", porque pede uma ação
  comercial, não remoção.

**D10. Robôs e contas de teste são clones de clientes.**
- Escolha: o injetor clona contas com todo o histórico e sinais sutis, que às vezes são um único sinal.
- Descartado: transformar clientes reais em robôs, o que apagaria uso verdadeiro da referência.
- Motivo: a conta inteira é defeito, e excluí-la recupera exatamente a verdade.

## Limpeza

**D11. Formato é staging; regra é clean.**
- Na staging: milissegundos do app 6.x, textos de tipo e UF e o parse de timestamps. É padronização conhecida e
  determinística.
- Na clean: tudo que exige julgamento, como fuso ambíguo, relógio, duplicata, limites e estados.
- A variante "ingênua" mantém a staging. Sem isso, o erro da ingênua seria dominado pela unidade nativa (milissegundos),
  e não pelos defeitos injetados.

**D12. Cada formato de timestamp é lido separadamente.**
- Achado: a primeira versão parseava tudo de uma vez com `utc=True`, e o pandas aplicava o offset `-03:00` das linhas
  web às linhas da TV, que não têm fuso. Resultado: +3 h em toda a TV. O sintoma foram 34 mil sessões "abertas demais".
- Correção: cada formato é lido no seu grupo. Um teste de regressão (`test_parse_client_ts_por_formato`) cobre o caso.

**D13. Fuso misturado é detectado pelo contrato de formato, não por estatística.**
- Regra: o web sempre manda offset, então hora do web sem offset é hora local e vai para UTC.
- Descartado: inferir o fuso pela distribuição de horas. Precisão menor, sem ganho.

**D14. Relógio errado se resolve por aparelho, com a hora do servidor.**
- Regra: mediana de (recebido − fim) acima de 30 min, com 60% das linhas consistentes, indica relógio deslocado.
  Linha isolada com desvio grande é atraso de sincronização, não relógio errado.
- Descartado: corrigir linha a linha, o que transformaria cada atraso offline em "relógio errado" e moveria o evento
  para o dia errado.

**D14b. Folga para unificar aparelhos = p99 do intervalo entre sessões do mesmo aparelho, medido nos dados.**
- Achado: com uma folga fixa de 14 dias, a primeira medição pegou só 66% das reinstalações; o intervalo mediano das
  perdidas era de 22 dias (gente que usa pouco).
- Escolha: em vez de calibrar olhando o registro (seria usar o gabarito), a folga passou a ser derivada do próprio uso:
  o p99 do intervalo entre sessões consecutivas de um aparelho (≈40 dias na referência). A regra continua exigindo zero
  uso simultâneo, que é o que protege contra unir dois aparelhos de verdade.

**D15. Pagamento duplicado: chave idempotente + janela de 1 h; fica a primeira entrega.**
- Chave: (fatura, tipo, tentativa, status, valor).
- Descartado: deduplicar só pelo id do gateway, porque webhook reentregue chega com id novo.
- Descartado: janela de um dia, porque a retentativa legítima de D+1 tem outro número de tentativa, mas Pix e boleto
  podem ter duas cobranças no mesmo dia.

**D16. Assinatura sobreposta vai para a quarentena, com faturas e pagamentos.**
- Escolha: quarentena e aviso ao financeiro, porque pode ter havido cobrança em dobro.
- Descartado: fechar a assinatura antiga na data da nova. A antiga continua com faturas pagas no período, e a nova não
  tem vínculo de reativação nem evento de upgrade. É duplicata, não troca de plano.

**D17. Preço divergente do SCD2 é corrigido, e o pagamento acompanha.**
- Descartado: manter o valor cobrado e só sinalizar.
- Motivo: o registro carregou o preço vencido do cache, mas o contrato é a tabela vigente na data. Se fosse cobrança real
  a menor, a alternativa certa seria sinalizar e gerar ajuste. O registro deixa a hipótese explícita.

**D18. Limites físicos limitam; não removem.**
- Regras:
  - maior que a duração do conteúdo: limita à duração;
  - negativo: usa fim − início quando os horários são válidos;
  - mais de 24 h no aparelho no dia: reduz proporcionalmente.
- Descartado: remover a reprodução, porque a reprodução existiu; só o número está errado.

**D19. Outlier estatístico só sinaliza.**
- Escolha: IQR, z-score robusto, sazonal e Isolation Forest marcam, mas não removem.
- Exceção: o Isolation Forest exclui das métricas quando a explicação é "robô" (muitas reproduções curtas por dia). A
  ablação `outlier_como_erro` mostra o custo de remover.

**D20. Nulos: UF nula da TV é MAR; imputa-se a região, não a UF.**
- Imputação: a região vem da moda das sessões da própria conta. A UF fica nula: não há como saber o estado, e o fuso usa
  o padrão do país.
- Telefone, nascimento e CEP são compatíveis com MCAR e não são usados nas métricas, então não são imputados.

**D21. Reprodução sem sessão não vai para a quarentena.**
- Escolha: fica sinalizada.
- Motivo: a sessão é chave lógica e se perde em falhas de ingestão da própria fonte. Perfil, aparelho e título existem.

## Carga

**D22. Incremental só no uso; assinatura e cobrança são foto completa.**
- Uso: sessões e reproduções chegam em lotes por `recebido_em`, são particionadas por mês do evento e regravadas por hash.
- Assinatura e cobrança: tabelas pequenas, vindas de uma foto completa do sistema. São recalculadas inteiras a cada
  execução.
- Descartado: incremental em tudo. Cobrança muda o passado (reembolso, contestação), e uma foto completa é a fonte
  confiável.

**D23. Detectores e regras com estado de aparelho usam tudo que já chegou.**
- Regras afetadas: perfil de relógio, unificação de aparelhos, robôs.
- Funcionamento: são recalculados a cada execução sobre todo o uso já ingerido. Se a decisão sobre um aparelho muda, o
  hash dos meses afetados muda, e só esses meses são recalculados.

**D24. Janela de atrasados de 30 dias, lotes de 7 dias.**
- Motivo: a sincronização offline vista vai até cerca de 20 dias. Com 30 dias, o mês anterior ainda pode ser reaberto
  sem reabrir o trimestre.
- A ablação `janela_0` mostra o custo de descartar atrasados.

## Avaliação

**D25. O "ingênuo" é a staging mais o mesmo código de mart.**
- Motivo: o mart não limpa nada. Assim, a diferença entre variantes é só a limpeza, nunca a forma de calcular.

**D26. O modelo de churn usa população e rótulo da verdade.**
- Motivo: isola o viés das FEATURES.
- Validação: o teste é fora do tempo (treino até set/2025, teste de dez/2025 a jun/2026), pontuado com as features da
  verdade. É o cenário de quem treina em dado sujo e usa o modelo no mundo real.

**D27. O erro médio conta a partir de jan/2024.**
- Motivo: de out a dez/2023 a base tem poucas centenas de contas, e o erro relativo explode sem significado.

## Dashboard

**D28. HTML estático com Plotly via CDN; dados embutidos no arquivo.**
- Escolha: os títulos dizem a conclusão e são gerados a partir dos números, para não ficarem desatualizados.
- Paleta da marca: Cobalt, Amber e Teal, validada para daltonismo e contraste nos temas claro e escuro.
- Descartado: um app com servidor. O GitHub Pages serve arquivos estáticos e o dashboard não precisa de backend.
