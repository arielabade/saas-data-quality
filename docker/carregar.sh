#!/usr/bin/env bash
# Carrega no MySQL só as tabelas que este projeto usa (lista em $TABELAS, na ordem das FKs).
# Adaptado de mysql/carregar.sh da base fonte; a fonte não é alterada.
set -euo pipefail
HOST=${MYSQL_HOST:-127.0.0.1}
DIR=${CSV_DIR:-/dados/csv}
MYSQL=(mysql -h "$HOST" -uroot --local-infile=1 cinelume)

for t in $TABELAS; do
  arq="$DIR/$t.csv.gz"
  [ -f "$arq" ] || { echo "faltando: $arq" >&2; exit 1; }
  cab=$(set +o pipefail; gzip -dc "$arq" 2>/dev/null | head -1 | tr -d '"\r')
  vars=""; sets=""
  IFS=',' read -ra cols <<< "$cab"
  for c in "${cols[@]}"; do vars+="@$c,"; sets+="\`$c\` = NULLIF(@$c, ''),"; done
  vars=${vars%,}; sets=${sets%,}
  fifo=$(mktemp -u /tmp/carga_XXXX); mkfifo "$fifo"
  gzip -dc "$arq" > "$fifo" &
  # FK desligada na carga parcial: tabelas fora do escopo (cupons, resgates) não são carregadas
  "${MYSQL[@]}" -e "SET SESSION foreign_key_checks=0; TRUNCATE TABLE \`$t\`;
    LOAD DATA LOCAL INFILE '$fifo' INTO TABLE \`$t\` CHARACTER SET utf8mb4
      FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"' ESCAPED BY ''
      LINES TERMINATED BY '\n' IGNORE 1 LINES ($vars) SET $sets;"
  wait; rm -f "$fifo"
  n=$("${MYSQL[@]}" -N -e "SELECT COUNT(*) FROM \`$t\`")
  esperado=$(( $(gzip -dc "$arq" | wc -l) - 1 ))
  echo "$(date +%T) $t: $n linhas"
  [ "$n" = "$esperado" ] || { echo "ERRO: $t tem $esperado no CSV e $n no banco" >&2; exit 2; }
done
echo "carga concluída"
