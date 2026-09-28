#!/bin/bash
# Cenário C2: 10 requisições na MESMA conexão persistente.
# Um único processo curl com 10 URLs reaproveita a conexão (HTTP/1.1 keep-alive).
# Rodar na máquina CLIENTE, com a captura já ativa na máquina do servidor.
# Uso: scripts/c2.sh <ip-do-servidor> [porta] [recurso]
HOST=${1:?uso: $0 <ip-do-servidor> [porta] [recurso]}
PORT=${2:-8080}
URL="http://$HOST:$PORT${3:-/medicao.html}"

args=()
for i in $(seq 10); do
  args+=(-o /dev/null "$URL")  # -o vale só para a URL seguinte, por isso um por URL
done

start=$(python3 -c 'import time; print(time.time())')
curl -s -w "status %{http_code}, conexões novas %{num_connects}, %{time_total}s\n" "${args[@]}"
end=$(python3 -c 'import time; print(time.time())')
python3 -c "print(f'C2 tempo no cliente: {($end - $start) * 1000:.1f} ms')"
