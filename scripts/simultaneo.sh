#!/bin/bash
# Evidência de atendimento simultâneo (item 5): rodar AO MESMO TEMPO em duas máquinas.
# Abre uma conexão "lenta" (requisição enviada pela metade) e, enquanto ela está pendente,
# faz requisições normais. O log do servidor mostra as conexões intercaladas.
# Uso: scripts/simultaneo.sh <ip-do-servidor> [porta]
HOST=${1:?uso: $0 <ip-do-servidor> [porta]}
PORT=${2:-8080}

python3 - "$HOST" "$PORT" <<'PY'
import socket, sys, time
host, port = sys.argv[1], int(sys.argv[2])
slow = socket.create_connection((host, port))
slow.sendall(b"GET /index.html HTTP/1.1\r\nHost: " + host.encode() + b"\r\n")  # sem a linha vazia
print("conexão lenta aberta (requisição incompleta)")
for i in range(5):
    t = time.time()
    with socket.create_connection((host, port)) as s:
        s.sendall(f"GET /texto.txt HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
        first_line = s.recv(4096).split(b"\r\n")[0].decode()
    print(f"requisição rápida {i + 1}: {first_line} em {(time.time() - t) * 1000:.1f} ms")
    time.sleep(0.5)
slow.sendall(b"Connection: close\r\n\r\n")
print("conexão lenta concluída:", slow.recv(4096).split(b"\r\n")[0].decode())
PY
