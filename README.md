# T1 – Servidor HTTP/1.1 sobre sockets TCP (Grupo 5)

Laboratório de Redes de Computadores – PUCRS.
Integrantes: `<Integrante 1>`, `<Integrante 2>`, `<Integrante 3>`.

Servidor HTTP/1.1 escrito em Python usando diretamente a API de sockets TCP
(`socket`, `bind`, `listen`, `accept`, `recv`, `sendall`). Nenhuma biblioteca de
HTTP é usada: parsing da requisição, percent-encoding e geração das respostas
são feitos no próprio `server.py`.

## Requisitos

- Python 3.9 ou superior (só biblioteca padrão; nada a instalar).
- Para as medições: Wireshark (inclui `tshark`) e `curl`.

## Execução

```bash
python3 server.py --port 8080 --root ./www
```

| Argumento   | Obrigatório | Padrão    | Descrição                                           |
|-------------|-------------|-----------|-----------------------------------------------------|
| `--port`    | sim         | –         | Porta TCP (use uma porta alta, > 1024)              |
| `--root`    | sim         | –         | Diretório raiz servido                              |
| `--host`    | não         | `0.0.0.0` | Endereço de bind. `0.0.0.0` = todas as interfaces IPv4; `::` = IPv6 **e** IPv4 (dual-stack) |
| `--timeout` | não         | `5`       | Timeout de conexão ociosa, em segundos              |
| `--quiet`   | não         | –         | Desliga o log de requisições no terminal            |

O servidor imprime um log por requisição e por abertura/fechamento de conexão,
com horário (ms), id da conexão, thread e IP:porta do cliente. `Ctrl+C` encerra.

### macOS: firewall e IP

- Na primeira execução o macOS pode perguntar se o Python pode **aceitar conexões
  de entrada**: clique em **Permitir**, senão as outras máquinas não conectam.
  (Ajustes do Sistema → Rede → Firewall → Opções, se precisar liberar depois.)
- IP da máquina: `ipconfig getifaddr en0` (Wi-Fi). O `ipconfig` do enunciado é do Windows.
- Teste de alcance a partir de outra máquina: `ping <ip>` e depois
  `curl -i http://<ip>:8080/`.

### Rede só IPv6 (hotspot de iPhone em algumas operadoras)

Se `ipconfig getifaddr en0` não mostra nada (ou mostra `192.0.0.2`, endereço interno do
CLAT do macOS, inalcançável por outras máquinas), a rede só tem IPv6:

```bash
python3 server.py --port 8080 --root ./www --host ::
```

- IPv6 do Mac: `ifconfig en0 | grep "autoconf secured" | grep -v deprecated | awk '{print $2}'`
- Teste do Windows: `ping -6 -n 4 <ipv6>` e `curl -i "http://[<ipv6>]:8080/"`. Em URLs o IPv6 vai **entre colchetes**.
- Os scripts aceitam o IPv6 puro (`scripts/c1.sh 2804:…`) e colocam os colchetes sozinhos.

### Ubuntu e Windows

| | Ubuntu | Windows |
|---|---|---|
| Rodar o servidor | `python3 server.py …` | `py server.py …` (instalar Python ≥ 3.9 de python.org) |
| IP da máquina | `ip -4 addr` ou `hostname -I` | `ipconfig` |
| Firewall | `ufw` costuma vir desligado; se ativo: `sudo ufw allow 8080/tcp` | aceitar o aviso do Firewall do Windows **marcando "Redes privadas"**; a rede Wi-Fi precisa estar como **Privada** (em Pública, as conexões de entrada são bloqueadas) |
| curl | `sudo apt install curl` se faltar | já vem instalado; no PowerShell usar **`curl.exe`** (`curl` sozinho é um alias de `Invoke-WebRequest`) |
| Scripts `.sh` | rodam direto | rodar no **Git Bash** ou no WSL (no PowerShell não funcionam) |
| ping (RTT) | `ping -c 20 <ip>` | `ping -n 20 <ip>` |
| Wireshark/tshark | `sudo apt install wireshark`, responder "sim" para capturar sem root e `sudo usermod -aG wireshark $USER` (relogar) | o instalador inclui o Npcap (deixar marcado); `tshark` fica em `C:\Program Files\Wireshark\` |
| Interface de captura | `wlp…`/`enp…` (ver `ip link`) | "Wi-Fi" ou "Ethernet" |

**WSL2:** serve como **cliente** (curl/scripts), mas **não** rode o servidor dentro do
WSL2. Ele fica atrás de uma NAT com IP próprio e as outras máquinas não alcançam
sem configurar redirecionamento de porta. Para servidor no Windows, use o Python do Windows.

## Estrutura

```
server.py              servidor
tests/test_server.py   testes automatizados (sockets crus, localhost)
scripts/               testes manuais e medições (rodar na máquina cliente)
www/                   diretório servido, incluindo a página do teste de interoperabilidade
capturas/              arquivos .pcapng dos cenários
relatorio/             relatório (Markdown → PDF) e imagens
```

## Testes

```bash
python3 -m unittest discover -s tests -v
```

Sobem o servidor em localhost numa porta livre (com timeout de 1 s) e cobrem:
status 200/400/403/404/405, HEAD, Content-Type, percent-encoding, travessia de
diretório (incluindo symlink), requisição fragmentada byte a byte, pipelining,
keep-alive, `Connection: close`, HTTP/1.0, timeout ocioso e cliente lento.

> localhost é só para desenvolvimento. Todas as evidências do relatório são entre máquinas distintas.

## Scripts (rodar na máquina **cliente**)

| Script | Uso | Para o relatório |
|---|---|---|
| `scripts/conformidade.sh <ip> [porta]` | um `curl` por status obrigatório | item 2 |
| `scripts/travessia.sh <ip> [porta]` | 5 tentativas de travessia (3 com percent-encoding) | item 3 |
| `scripts/simultaneo.sh <ip> [porta]` | conexão lenta + requisições rápidas; rodar nas 2 máquinas ao mesmo tempo | item 5 |
| `scripts/c1.sh <ip> [porta] [recurso]` | 10 requisições, uma conexão nova cada (`Connection: close`) | itens 7–9 |
| `scripts/c2.sh <ip> [porta] [recurso]` | 10 requisições numa única conexão persistente | itens 7–9 |
| `scripts/metricas.py <pcap> [--port N]` | extrai handshakes, pacotes, bytes, tempo e overhead de uma captura | itens 7–8 |

O recurso padrão das medições é `/medicao.html` (~4,6 KB).

## Procedimento de medição (C1 e C2)

1. Máquina cliente: `ping -c 20 <ip-servidor>` e anotar o RTT médio.
2. Máquina servidor: `python3 server.py --port 8080 --root ./www`.
3. Máquina servidor: iniciar a captura (Wireshark com filtro de captura
   `tcp port 8080`, ou pelo terminal):
   ```bash
   tshark -i en0 -f "tcp port 8080" -w capturas/c1.pcapng
   ```
4. Máquina cliente: `scripts/c1.sh <ip-servidor>`.
5. Esperar ~6 s (o último FIN/timeout) e parar a captura (`Ctrl+C`).
6. Repetir os passos 3–5 com `c2.pcapng` e `scripts/c2.sh`.
7. `python3 scripts/metricas.py capturas/c1.pcapng` (e `c2.pcapng`).

Rodar cada cenário 3 vezes e guardar em `capturas/` o par representativo (mediana).
