#!/bin/bash
# Evidência de atendimento simultâneo (item 5).
# Abre uma requisição LENTA, que manda uma linha de cabeçalho por segundo durante
# <segundos>, e, enquanto ela não termina, faz uma requisição rápida por segundo em
# outras conexões. Se o servidor bloqueasse na requisição lenta, as rápidas esperariam.
# Durante essa janela, acesse o servidor de OUTRA máquina (ex.: navegador do celular):
# o log do servidor mostra as duas máquinas atendidas ao mesmo tempo.
# <ip-do-servidor> pode ser IPv4 (192.168.0.10) ou IPv6 (2804:...).
# Uso: scripts/simultaneo.sh <ip-do-servidor> [porta] [segundos]   (padrão: 15 s)
HOST=${1:?uso: $0 <ip-do-servidor> [porta] [segundos]}
HOST=${HOST#[}; HOST=${HOST%]}  # aceita o IP com ou sem colchetes
PORT=${2:-8080}
SECONDS_TOTAL=${3:-15}

# acha um Python que funcione (no Windows, "python3" pode ser só o atalho da Microsoft Store)
for candidate in python3 python py; do
  if "$candidate" -c "" >/dev/null 2>&1; then PY=$candidate; break; fi
done
: "${PY:?Python não encontrado}"

"$PY" - "$HOST" "$PORT" "$SECONDS_TOTAL" <<'PY'
import socket, sys, time
host, port, total = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
host_header = f"[{host}]" if ":" in host else host

start = time.time()
slow = socket.create_connection((host, port))
slow.sendall(f"GET /index.html HTTP/1.1\r\nHost: {host_header}\r\n".encode())
print(f"requisição lenta iniciada: 1 linha de cabeçalho por segundo durante {total} s")
for i in range(1, total + 1):
    # cabeçalho a cada 1 s: o servidor recebe dados e não dispara o timeout ocioso
    slow.sendall(f"X-Lento-{i}: {i}\r\n".encode())
    t = time.time()
    with socket.create_connection((host, port)) as s:
        s.sendall(f"GET /texto.txt HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n\r\n".encode())
        first_line = s.recv(4096).split(b"\r\n")[0].decode()
    print(f"[{time.time() - start:5.1f} s] requisição rápida {i}: {first_line} em {(time.time() - t) * 1000:.1f} ms")
    time.sleep(max(0.0, 1 - (time.time() - t)))
slow.sendall(b"Connection: close\r\n\r\n")
print(f"[{time.time() - start:5.1f} s] requisição lenta concluída:", slow.recv(4096).split(b"\r\n")[0].decode())
PY
