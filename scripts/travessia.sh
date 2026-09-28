#!/bin/bash
# Tentativas de travessia de diretório (item 3 do relatório). Todas devem dar 403.
# --path-as-is impede o curl de normalizar o '..' antes de enviar.
# Uso: scripts/travessia.sh <ip-do-servidor> [porta]
HOST=${1:?uso: $0 <ip-do-servidor> [porta]}
PORT=${2:-8080}
BASE="http://$HOST:$PORT"

for target in \
  "/../../etc/passwd" \
  "/%2e%2e/%2e%2e/etc/passwd" \
  "/..%2f..%2f..%2fetc%2fpasswd" \
  "/img/../../../etc/passwd" \
  "/%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd"; do
  echo "=================================================================="
  echo "\$ curl -s -i --path-as-is \"$BASE$target\""
  echo "------------------------------------------------------------------"
  curl -s -i --path-as-is "$BASE$target"
  echo
done
