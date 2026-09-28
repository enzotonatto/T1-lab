#!/bin/bash
# Gera a tabela de conformidade (item 2 do relatório): uma requisição curl por status.
# Uso: scripts/conformidade.sh <ip-do-servidor> [porta]
HOST=${1:?uso: $0 <ip-do-servidor> [porta]}
PORT=${2:-8080}
BASE="http://$HOST:$PORT"

run() {
  echo "=================================================================="
  printf '$'; printf ' %q' "$@"; echo  # %q mostra \r\n de forma legível
  echo "------------------------------------------------------------------"
  "$@"
  echo
}

run curl -s -i "$BASE/index.html"                                    # 200
run curl -s -I "$BASE/index.html"                                    # 200 (HEAD)
run curl -s -i --request-target "/index.html extra" "$BASE/"         # 400: request line com 4 partes
run curl -s -i -H $'X-Ok: 1\r\nCabecalhoSemDoisPontos' "$BASE/"      # 400: linha de cabeçalho sem ':'
run curl -s -i --path-as-is "$BASE/../../etc/passwd"                 # 403
run curl -s -i "$BASE/nao-existe.html"                               # 404
run curl -s -i -X POST -d "a=1" "$BASE/index.html"                   # 405
run curl -s -i -X DELETE "$BASE/index.html"                          # 405
