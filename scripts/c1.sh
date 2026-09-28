#!/bin/bash
# Cenário C1: 10 requisições, cada uma em uma conexão TCP nova (Connection: close).
# Rodar na máquina CLIENTE, com a captura já ativa na máquina do servidor.
# Uso: scripts/c1.sh <ip-do-servidor> [porta] [recurso]
HOST=${1:?uso: $0 <ip-do-servidor> [porta] [recurso]}
PORT=${2:-8080}
URL="http://$HOST:$PORT${3:-/medicao.html}"

start=$(python3 -c 'import time; print(time.time())')
for i in $(seq 10); do
  curl -s -o /dev/null -H "Connection: close" \
       -w "req $i: status %{http_code}, conexões novas %{num_connects}, %{time_total}s\n" "$URL"
done
end=$(python3 -c 'import time; print(time.time())')
python3 -c "print(f'C1 tempo no cliente: {($end - $start) * 1000:.1f} ms')"
