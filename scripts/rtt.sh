#!/bin/bash
# RTT entre cliente e servidor (item 6 do relatório): ping + mínimo, mediana, média e máximo.
# Em Wi-Fi poucos valores muito altos puxam a média para cima; a mediana é mais confiável.
# Intervalo de 0,2 s entre pacotes: com 1 s o rádio Wi-Fi entra em economia de energia
# entre um ping e outro e o RTT fica inflado.
# Uso (Linux/macOS): scripts/rtt.sh <ip-do-servidor> [quantidade]   (padrão: 50)
HOST=${1:?uso: $0 <ip-do-servidor> [quantidade]}
COUNT=${2:-50}

# idioma neutro: em português o ping do Linux espera vírgula decimal ("0,2") e escreve
# "tempo=" em vez de "time=", e o awk lê "61.2" como 61. Assim funciona em qualquer sistema.
export LC_ALL=C

ping -c "$COUNT" -i 0.2 "$HOST" | tee /dev/stderr \
  | grep -oE 'time[=<][0-9.]+' | cut -c6- | sort -n \
  | awk '{ v[NR] = $1; sum += $1 }
         END {
           if (NR == 0) { print "nenhuma resposta"; exit 1 }
           median = (NR % 2) ? v[(NR + 1) / 2] : (v[NR / 2] + v[NR / 2 + 1]) / 2
           printf "\nRTT (%d respostas): mínimo %.2f ms | mediana %.2f ms | média %.2f ms | máximo %.2f ms\n",
                  NR, v[1], median, sum / NR, v[NR]
         }'
