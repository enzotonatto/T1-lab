#!/bin/bash
# Cenário C2: 10 requisições na MESMA conexão persistente.
# Um único processo curl com 10 URLs reaproveita a conexão (HTTP/1.1 keep-alive).
# Rodar na máquina CLIENTE, com a captura já ativa na máquina do servidor.
# O 'time' mostra o tempo no cliente; a métrica oficial é o tempo na captura.
# <ip-do-servidor> pode ser IPv4 (192.168.0.10) ou IPv6 (2804:...).
# Uso: scripts/c2.sh <ip-do-servidor> [porta] [recurso]
HOST=${1:?uso: $0 <ip-do-servidor> [porta] [recurso]}
HOST=${HOST#[}; HOST=${HOST%]}  # aceita o IP com ou sem colchetes
URL_HOST=$HOST
[[ $HOST == *:* ]] && URL_HOST="[$HOST]"  # IPv6 vai entre colchetes na URL
PORT=${2:-8080}
URL="http://$URL_HOST:$PORT${3:-/medicao.html}"

args=()
for i in $(seq 10); do
  args+=(-o /dev/null "$URL")  # -o vale só para a URL seguinte, por isso um por URL
done

time curl -s -w "status %{http_code}, conexões novas %{num_connects}, %{time_total}s\n" "${args[@]}"
