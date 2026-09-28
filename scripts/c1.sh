#!/bin/bash
# Cenário C1: 10 requisições, cada uma em uma conexão TCP nova (Connection: close).
# Rodar na máquina CLIENTE, com a captura já ativa na máquina do servidor.
# O 'time' mostra o tempo no cliente; a métrica oficial é o tempo na captura.
# <ip-do-servidor> pode ser IPv4 (192.168.0.10) ou IPv6 (2804:...).
# Uso: scripts/c1.sh <ip-do-servidor> [porta] [recurso]
HOST=${1:?uso: $0 <ip-do-servidor> [porta] [recurso]}
HOST=${HOST#[}; HOST=${HOST%]}  # aceita o IP com ou sem colchetes
URL_HOST=$HOST
[[ $HOST == *:* ]] && URL_HOST="[$HOST]"  # IPv6 vai entre colchetes na URL
PORT=${2:-8080}
URL="http://$URL_HOST:$PORT${3:-/medicao.html}"

time for i in $(seq 10); do
  curl -s -o /dev/null -H "Connection: close" \
       -w "req $i: status %{http_code}, conexões novas %{num_connects}, %{time_total}s\n" "$URL"
done
