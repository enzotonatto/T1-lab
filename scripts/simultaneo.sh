#!/bin/bash
# Evidência de atendimento simultâneo (item 5): rodar AO MESMO TEMPO em duas máquinas.
# Abre uma conexão "lenta" (requisição enviada pela metade) e, enquanto ela está pendente,
# faz requisições normais. O log do servidor mostra as conexões intercaladas.
# <ip-do-servidor> pode ser IPv4 (192.168.0.10) ou IPv6 (2804:...).
# Uso: scripts/simultaneo.sh <ip-do-servidor> [porta]
HOST=${1:?uso: $0 <ip-do-servidor> [porta]}
HOST=${HOST#[}; HOST=${HOST%]}  # aceita o IP com ou sem colchetes
URL_HOST=$HOST
[[ $HOST == *:* ]] && URL_HOST="[$HOST]"  # IPv6 vai entre colchetes na URL
PORT=${2:-8080}

# acha um Python que funcione (no Windows, "python3" pode ser só o atalho da Microsoft Store)
for candidate in python3 python py; do
  if "$candidate" -c "" >/dev/null 2>&1; then PY=$candidate; break; fi
done
: "${PY:?Python não encontrado}"

"$PY" - "$HOST" "$PORT" <<'PY'
import socket, sys, time
host, port = sys.argv[1], int(sys.argv[2])
host_header = f"[{host}]" if ":" in host else host
slow = socket.create_connection((host, port))
slow.sendall(f"GET /index.html HTTP/1.1\r\nHost: {host_header}\r\n".encode())  # sem a linha vazia
print("conexão lenta aberta (requisição incompleta)")
for i in range(5):
    t = time.time()
    with socket.create_connection((host, port)) as s:
        s.sendall(f"GET /texto.txt HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n\r\n".encode())
        first_line = s.recv(4096).split(b"\r\n")[0].decode()
    print(f"requisição rápida {i + 1}: {first_line} em {(time.time() - t) * 1000:.1f} ms")
    time.sleep(0.5)
slow.sendall(b"Connection: close\r\n\r\n")
print("conexão lenta concluída:", slow.recv(4096).split(b"\r\n")[0].decode())
PY
