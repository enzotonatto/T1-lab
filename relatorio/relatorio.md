---
title: T1 – Servidor HTTP/1.1 sobre sockets TCP
subtitle: Laboratório de Redes de Computadores – Grupo 5
author: Enzo Augusto Tonatto, Matheus Seibt, Rafael Melo Rothmann
date: 05/10/2026
---

# 1. Arquitetura

**Ambiente.** Servidor num notebook com macOS, IP `192.168.15.9`; cliente
num notebook com Ubuntu, IP `192.168.15.15`; os dois na mesma Wi-Fi doméstica, em IPv4. Segundo cliente para o teste de
simultaneidade: um iPhone na mesma Wi-Fi, IP `192.168.15.8`. Servidor escutando em
`0.0.0.0:8080`, raiz `./www`.

O servidor também aceita `--host ::` (socket `AF_INET6` com `IPV6_V6ONLY` desligado, que
atende IPv6 e IPv4), usado nos testes preliminares num hotspot de celular só IPv6.

**Estrutura.** Um único arquivo, `server.py` (Python 3, só biblioteca padrão):

| Etapa | Função | O que faz |
|---|---|---|
| Aceitar conexões | `main` | `socket` → `bind(0.0.0.0, porta)` → `listen` → laço de `accept`; cada conexão vai para uma thread nova |
| Ler o fluxo de bytes | `handle_connection` | acumula `recv()` num buffer até achar `\r\n\r\n`; o que vem depois fica no buffer para a próxima requisição; descarta um eventual corpo (`Content-Length`) |
| Interpretar | `parse_request` | request line com exatamente 3 partes, versão `HTTP/1.0` ou `HTTP/1.1`, cabeçalhos `nome: valor` (nome sem espaços, comparação sem diferenciar maiúsculas) |
| Resolver o caminho | `resolve_path`, `percent_decode` | tira a query, decodifica `%XX`, rejeita `%00`, aplica `realpath` e verifica com `commonpath` se o resultado está dentro do root |
| Responder | `handle_request`, `send_file`, `send_error` | monta a linha de status e os cabeçalhos obrigatórios; envia o arquivo em blocos de 64 KB; HEAD envia só o cabeçalho |
| Persistência | `wants_keep_alive` | HTTP/1.1 persistente por padrão; `Connection: close` encerra; HTTP/1.0 só persiste com `keep-alive`; timeout ocioso de 5 s via `settimeout` |

**Concorrência: uma thread por conexão.** Cada `accept()` dispara uma
`threading.Thread` que atende todas as requisições daquela conexão e fecha o
socket no fim. Justificativa:

- O código de cada conexão é sequencial e bloqueante (recv → parse → send),
  fácil de ler e de explicar; uma conexão lenta bloqueia só a sua thread.
- O timeout ocioso sai de graça: `settimeout(5)` no socket da conexão faz o
  `recv()` levantar `socket.timeout`.
- A carga do trabalho (poucas máquinas, navegador abrindo até ~6 conexões) é
  pequena; o custo de memória de uma thread por conexão não pesa. Em Python o
  GIL não atrapalha, porque as threads passam quase todo o tempo bloqueadas em I/O
  (que libera o GIL).
- Alternativa considerada: I/O não bloqueante com `selectors`. Escala melhor
  para milhares de conexões, mas exige uma máquina de estados por conexão
  (buffer parcial, envio parcial, timeouts manuais), o que é mais complexo sem
  benefício na escala do trabalho.

**Decisões de conformidade.**

- Terminador de linha: só CRLF, como define o enunciado.
- Cabeçalho maior que 8 KB → 400.
- Depois de um 400 a conexão é fechada, porque não dá para saber onde começa a
  próxima requisição no fluxo. Depois de 403, 404 e 405 a conexão continua.
- `Host` ausente não gera 400 (a RFC 9112 pediria), para aceitar testes manuais
  com `nc`/`telnet`.
- Cabeçalho e primeiro bloco do corpo vão num único `sendall`. Com dois `send()`
  pequenos seguidos, o algoritmo de Nagle seguraria o segundo segmento até
  chegar o ACK do primeiro, e o cliente atrasa esse ACK (delayed ACK). Isso
  somaria dezenas de ms por resposta e distorceria as medições.

# 2. Tabela de conformidade

Gerada com `scripts/conformidade.sh 192.168.15.9` executado no Ubuntu
(saída completa em `relatorio/evidencias/conformidade.txt`). Todas as respostas
trazem `Date` (IMF-fixdate, GMT), `Server: LabRedes-T1-Grupo5/1.0`,
`Content-Type` e `Content-Length`.

| Status | Requisição (`curl`) | Resposta obtida |
|---|---|---|
| 200 | `curl -i http://192.168.15.9:8080/index.html` | `HTTP/1.1 200 OK`, `Content-Type: text/html; charset=utf-8`, `Content-Length: 1404` + corpo |
| 200 (HEAD) | `curl -I http://192.168.15.9:8080/index.html` | `HTTP/1.1 200 OK`, mesmos cabeçalhos, `Content-Length: 1404`, sem corpo |
| 400 | `curl -i --request-target "/index.html extra" http://192.168.15.9:8080/` | `HTTP/1.1 400 Bad Request`, `Content-Length: 139`, `Connection: close` (request line com 4 partes) |
| 400 | `curl -i -H $'X-Ok: 1\r\nCabecalhoSemDoisPontos' http://192.168.15.9:8080/` | `HTTP/1.1 400 Bad Request`, `Content-Length: 139`, `Connection: close` (linha de cabeçalho sem `:`) |
| 403 | `curl -i --path-as-is http://192.168.15.9:8080/../../etc/passwd` | `HTTP/1.1 403 Forbidden`, `Content-Length: 135` |
| 404 | `curl -i http://192.168.15.9:8080/nao-existe.html` | `HTTP/1.1 404 Not Found`, `Content-Length: 135` |
| 405 | `curl -i -X POST -d "a=1" http://192.168.15.9:8080/index.html` | `HTTP/1.1 405 Method Not Allowed`, `Allow: GET, HEAD`, `Content-Length: 153` |
| 405 | `curl -i -X DELETE http://192.168.15.9:8080/index.html` | `HTTP/1.1 405 Method Not Allowed`, `Allow: GET, HEAD`, `Content-Length: 153` |

# 3. Demonstração de segurança (travessia de diretório)

Gerada com `scripts/travessia.sh 192.168.15.9` no Ubuntu (saída completa em
`relatorio/evidencias/travessia.txt`). `--path-as-is` impede o `curl` de
normalizar o `..` antes de enviar. As cinco tentativas foram rejeitadas:

| # | Requisição enviada | Técnica | Resposta |
|---|---|---|---|
| 1 | `GET /../../etc/passwd` | `..` literal | `403 Forbidden` |
| 2 | `GET /%2e%2e/%2e%2e/etc/passwd` | `.` codificado | `403 Forbidden` |
| 3 | `GET /..%2f..%2f..%2fetc%2fpasswd` | `/` codificado | `403 Forbidden` |
| 4 | `GET /img/../../../etc/passwd` | sai do root a partir de um subdiretório | `403 Forbidden` |
| 5 | `GET /%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd` | tudo codificado | `403 Forbidden` |

Por que funciona: o caminho é **decodificado antes** da verificação (então
`%2e%2e` vira `..`), e a verificação é feita sobre o caminho **canônico**
(`realpath` resolve `..` e links simbólicos), comparando componentes inteiros
com `commonpath` (`/www2` não passa como se estivesse dentro de `/www`). Os
testes automatizados também cobrem um link simbólico dentro de `www/` apontando
para fora (403).

![As três primeiras tentativas de travessia e as respostas do servidor](img/travessia.png)

# 4. Captura de uma transação completa

Captura `capturas/transacao.pcapng`: `curl http://192.168.15.9:8080/index.html`
feito do Ubuntu (192.168.15.15) e capturado no Mac (192.168.15.9), filtro
`tcp.port == 8080`. Uma única conexão, 12 pacotes, 19 ms do SYN ao último ACK.

![Transação completa no Wireshark (filtro `tcp.port == 8080`)](img/transacao.png)

| Pacote | Origem → destino | Flags | Dados | Papel |
|---|---|---|---|---|
| 1 | Ubuntu → Mac | SYN | 0 | **Handshake** (1/3), MSS 1460 |
| 2 | Mac → Ubuntu | SYN, ACK | 0 | **Handshake** (2/3) |
| 3 | Ubuntu → Mac | ACK | 0 | **Handshake** (3/3), 5,5 ms após o SYN-ACK = 1 RTT |
| 4 | Ubuntu → Mac | PSH, ACK | 91 B | **Requisição**: `GET /index.html HTTP/1.1` |
| 5 | Mac → Ubuntu | ACK | 0 | ACK da requisição |
| 6 | Mac → Ubuntu | ACK | 1448 B | **Resposta**: `HTTP/1.1 200 OK` + cabeçalhos + início do corpo (1 MSS) |
| 7 | Mac → Ubuntu | PSH, ACK | 106 B | **Resposta**: fim do corpo (1404 B de corpo no total) |
| 8 | Ubuntu → Mac | ACK | 0 | ACK da resposta |
| 9 | Ubuntu → Mac | FIN, ACK | 0 | **Encerramento**: cliente fecha (o curl termina) |
| 10 | Mac → Ubuntu | ACK | 0 | **Encerramento**: ACK do FIN do cliente |
| 11 | Mac → Ubuntu | FIN, ACK | 0 | **Encerramento**: servidor fecha |
| 12 | Ubuntu → Mac | ACK | 0 | **Encerramento**: ACK final |

O cabeçalho e o primeiro bloco do corpo saem no mesmo segmento (pacote 6),
efeito do `sendall` único descrito na seção 1.

O Mac respondeu ao SYN em 0,5 ms (pacote 2); do SYN-ACK ao ACK do cliente (pacote 3)
passaram 5,5 ms, que é 1 RTT medido no lado do servidor. Como o `curl` não pediu
`Connection: close`, quem encerra é o cliente (pacote 9): o `recv()` do servidor
devolve vazio, `handle_connection` sai do laço e o `finally` fecha o socket, o que
gera o FIN do servidor (pacote 11).

# 5. Evidência de atendimento simultâneo

O Ubuntu (192.168.15.15) executou `scripts/simultaneo.sh 192.168.15.9`: uma
requisição **lenta**, que envia uma linha de cabeçalho por segundo e só termina
após ~15 s, e, em paralelo, uma requisição rápida por segundo em outras conexões.
Durante essa janela, o navegador do celular (192.168.15.8) carregou a página.

Trecho de `capturas/servidor.log` (cada conexão tem sua thread `tN`):

```
18:19:50.881 [conn 26 | t26] conexão aberta de 192.168.15.15:48744      <- requisição lenta
18:19:50.886 [conn 27 | t27] conexão aberta de 192.168.15.15:48748
18:19:50.887 [conn 27 | t27] "GET /texto.txt HTTP/1.1" 200 50B
...
18:19:55.303 [conn 32 | t32] conexão aberta de 192.168.15.8:60952       <- celular
18:19:55.303 [conn 32 | t32] "GET / HTTP/1.1" 200 1404B
18:19:55.318 [conn 32 | t32] "GET /style.css HTTP/1.1" 200 340B
18:19:55.324 [conn 33 | t33] conexão aberta de 192.168.15.8:60953
18:19:55.324 [conn 33 | t33] "GET /img/logo.png HTTP/1.1" 200 18561B
...
18:20:06.063 [conn 26 | t26] "GET /index.html HTTP/1.1" 200 1404B       <- lenta termina
18:20:06.063 [conn 26 | t26] conexão fechada com 192.168.15.15:48744: Connection: close, 1 requisição(ões)
```

A conexão 26 ficou aberta por 15,2 s; nesse intervalo o servidor atendeu as
requisições rápidas do Ubuntu e as conexões do celular. Na captura
`capturas/simultaneo.pcapng`, as 3 conexões do celular começam e terminam dentro
da conexão lenta do Ubuntu (Wireshark: Statistics → Conversations → TCP).

A captura começou cerca de 2 s depois de a conexão lenta abrir (o SYN dela não foi
capturado); por isso o Wireshark mostra 13,2 s de duração, e não os 15,2 s do log.
Na captura, as conexões do celular começam 2,3 s depois e terminam 9,4 s depois disso
(aos 11,8 s), ainda dentro dos 13,2 s da conexão lenta.

![Conversas TCP em simultaneo.pcapng: as conexões do celular dentro da conexão lenta](img/conversations.png)

# 6. RTT medido

`scripts/rtt.sh 192.168.15.9` no Ubuntu antes de cada rodada (50 pings, intervalo
de 0,2 s; resumos em `relatorio/evidencias/ping_N.txt`):

| Rodada | Mínimo | **Mediana** | Média | Máximo |
|---|---|---|---|---|
| 1 | 5,32 ms | **7,09 ms** | 17,77 ms | 203,00 ms |
| 2 | 5,50 ms | **6,72 ms** | 15,73 ms | 89,80 ms |
| 3 | 4,50 ms | **7,04 ms** | 14,06 ms | 90,40 ms |

RTT de referência: **≈ 7 ms** (mediana). A média é 2 a 2,5 vezes maior porque
poucos pings muito lentos (até 203 ms), típicos de Wi-Fi, puxam a média para cima.

RTT medido nas próprias capturas (do SYN-ACK enviado pelo servidor até o ACK
do cliente): mediana de **5,2 ms** em `c1.pcapng` (10 handshakes).

**Por que o ping dá mais que os handshakes.** As duas medidas não observam a mesma
coisa. O RTT dos handshakes é medido pela captura no próprio servidor, do SYN-ACK
saindo até o ACK chegando: só entram a rede e a resposta do kernel do cliente. O ping
é medido pelo programa `ping`, no cliente. A causa mais provável da diferença é o
Wi-Fi: o ping envia um pacote a cada 0,2 s, e nesse intervalo a placa de rede (do
notebook ou do roteador) pode entrar em modo de economia de energia e atrasar o pacote
seguinte. Em C1 e C2 o tráfego é contínuo por 65 a 136 ms, e o rádio fica ativo. Os
picos de até 203 ms e a média 2 a 2,5 vezes maior que a mediana mostram essa
variação. Por isso o item 9 usa como referência o RTT medido nas próprias capturas.

# 7. Comparação C1 × C2

10 requisições sequenciais a `/medicao.html` (4 636 bytes de corpo).
C1: `scripts/c1.sh` (um processo `curl` com 10 URLs e `Connection: close`: o servidor fecha
após cada resposta e o curl abre uma conexão nova por requisição).
C2: `scripts/c2.sh` (um processo `curl`, uma conexão persistente).
Métricas extraídas com `scripts/metricas.py`. Foram feitas 3 rodadas de cada; a
rodada 1 é a mediana de tempo nos dois cenários e é a entregue como
`capturas/c1.pcapng` e `capturas/c2.pcapng`.

| Métrica | C1 | C2 | Economia de C2 |
|---|---|---|---|
| Handshakes TCP completos | 10 | 1 | 9 handshakes |
| Total de pacotes | 152 | 78 | **48,7 %** |
| Bytes totais | 59 402 | 53 958 | **9,2 %** |
| Tempo total | 136,1 ms | 65,3 ms | **52,0 %** |

Economia % = (C1 − C2) / C1 × 100.

Todas as rodadas:

| Rodada | C1: pacotes / bytes / tempo | C2: pacotes / bytes / tempo |
|---|---|---|
| 1 | 152 / 59 402 / 136,1 ms | 78 / 53 958 / 65,3 ms |
| 2 | 150 / 59 270 / 223,2 ms | 84 / 54 354 / 63,0 ms |
| 3 | 153 / 59 468 / 129,3 ms | 81 / 54 156 / 68,8 ms |

# 8. Overhead de conexão (C1)

Dados de `c1.pcapng` e `c2.pcapng`:

- Um handshake = 3 pacotes: SYN (74 B) + SYN-ACK (78 B) + ACK (66 B) = **218 B**.
- Um encerramento iniciado pelo cliente = 4 pacotes: FIN, ACK, FIN, ACK (66 B cada)
  = **264 B**.
- Abrir e fechar uma conexão: **7 pacotes, 482 B**. É exatamente o que aparece em C2,
  que usa uma conexão só.

Em C1, abrir e fechar as 10 conexões custa pelo menos 10 × 7 = **70 pacotes (46 % dos
152)**, mas só 10 × 482 = **4 820 B (8 % dos 59 402 B)**. A diferença entre C1 e C2 se
decompõe exatamente em três parcelas:

| Origem | Pacotes | Bytes |
|---|---|---|
| 9 conexões a mais × (3 de abertura + 4 de encerramento) | 63 | 4 338 |
| `Connection: close\r\n` (19 B) na requisição e na resposta, 10 vezes | 0 | 380 |
| ACKs a mais do cliente (66 B cada) | 11 | 726 |
| **Total (C1 − C2)** | **74** | **5 444** |

Abrir e fechar conexões responde por 85 % dos pacotes extras e 80 % dos bytes extras.
Por isso a economia de C2 é grande em pacotes (48,7 %) e pequena em bytes (9,2 %): os
pacotes de controle são pequenos (66 a 78 B), enquanto o conteúdo das 10 respostas
(cerca de 49 KB) é o mesmo nos dois cenários.

Os 11 ACKs a mais vêm do cliente: em C1 ele enviou em média 2,2 ACKs por resposta,
contra 1,1 em C2. Numa conexão nova, o TCP do Linux confirma os primeiros segmentos
com mais frequência (modo *quick ACK*); numa conexão longa, passa a agrupar as
confirmações (ACK atrasado).

O encerramento também muda de forma. Como o cliente envia `Connection: close`, em C1
quem fecha primeiro é o **servidor**: logo depois da resposta, `handle_connection` sai
do laço e o `finally` chama `conn.close()`. O FIN do servidor sai antes de o cliente
confirmar os dados, e os ACKs desses dados chegam depois dele; em 5 ocasiões os FINs
dos dois lados se cruzam e o servidor repete o FIN na última confirmação. Por isso
`metricas.py` conta 62 pacotes de encerramento em C1 (6,2 por conexão, incluindo os
ACKs dos dados que chegam depois do primeiro FIN), contra 4 em C2, onde quem fecha é o
cliente.

# 9. Análise em função do RTT

Rodada 1, tempos medidos na captura do servidor (soma de cada trecho):

| Trecho | C1 | C2 | C1 − C2 |
|---|---|---|---|
| Handshakes (SYN → GET) | 63,5 ms (10 ×) | 6,4 ms (1 ×) | **+57,1 ms** |
| Servidor (GET → fim da resposta) | 8,8 ms | 6,8 ms | +2,0 ms |
| Cliente entre requisições (fim da resposta → próximo SYN ou GET) | 59,3 ms | 41,4 ms | +17,9 ms |
| Encerramento final (fim da última resposta → último pacote) | 4,5 ms | 10,7 ms | −6,2 ms |
| **Tempo total** | **136,1 ms** | **65,3 ms** | **+70,8 ms** |

Em C2, cada requisição custa cerca de 1 RTT: a resposta vai até o cliente e o GET
seguinte volta ao servidor (mediana de 4,8 ms entre GETs). Em C1, cada requisição
custa cerca de 2 RTT, porque antes do GET o cliente precisa abrir uma conexão nova, e
nenhum byte da requisição pode sair antes do handshake (SYN → SYN-ACK → ACK). Na
captura, o intervalo entre o SYN e o GET de cada conexão tem mediana de 5,4 ms, em
linha com o RTT de 5,2 ms medido nos handshakes (item 6). Como C2 também faz um
handshake, o esperado é que C1 gaste **9 RTT a mais**.

A tabela mostra de onde vêm os 70,8 ms:

- **9 handshakes a mais: 57,1 ms (81 % da diferença)**, média de 6,3 ms cada, ou seja,
  1 RTT por conexão nova. É o custo previsto.
- **Cliente trocando de conexão: 17,9 ms**, cerca de 2 ms por conexão. Antes de cada
  requisição de C1, o cliente fecha a conexão antiga e abre uma nova (o FIN do cliente
  e o SYN seguinte chegam juntos ao servidor). Esse custo não depende da rede.
- **Servidor: 2,0 ms**, cerca de 0,2 ms por requisição, provavelmente para aceitar a
  conexão e criar a thread de cada conexão nova.
- **Encerramento final: −6,2 ms.** Em C2 o cliente só fecha a conexão depois de
  receber a última resposta e ainda espera o FIN do servidor (cerca de 2 RTT no fim da
  captura); em C1 o servidor envia o FIN logo depois da resposta (cerca de 1 RTT).

Em RTTs: 70,8 / 5,2 ≈ 13,6 RTT, que são os 9 RTT dos handshakes mais custos que não
dependem da rede (≈ 13,7 ms no total). Dividindo pela mediana do ping (7,09 ms), o
resultado dá ≈ 10 RTT, mas só porque o ping superestima o RTT (item 6).

Dois cuidados de medição. Primeiro, C1 e C2 usam um único processo `curl` com 10 URLs:
numa medição anterior, com um `curl` por requisição, cada processo novo somava ~150 ms
entre uma conexão e a seguinte no Windows, muito mais que o RTT, e escondia o efeito
do handshake. Segundo, a rodada 2 de C1 (223,2 ms) teve um único intervalo de 92 ms
sem pacotes, um pico de latência do Wi-Fi; por isso a análise usa a rodada mediana.

# 10. Conclusão

O servidor atende os requisitos das duas partes: parsing sobre o fluxo de bytes do TCP,
os códigos de status obrigatórios, proteção contra travessia de diretório, uma thread
por conexão e conexões persistentes com timeout ocioso.

Com 10 requisições, a conexão persistente economizou 70,8 ms (52 % do tempo de C1),
74 pacotes (48,7 %) e 5 444 B (9,2 %). O custo extra de abrir uma conexão por
requisição é aproximadamente

> (número de conexões novas) × (1 RTT de handshake + custo fixo por conexão)

Nesta rede, com RTT ≈ 5 ms, o termo do RTT já respondeu por 81 % da diferença. A
conexão persistente traria um ganho ainda maior:

- **Com RTT maior.** O custo do handshake cresce linearmente com o RTT. Com 100 ms
  (servidor em outro continente, rede móvel ou satélite), os mesmos 9 handshakes
  custariam cerca de 900 ms em vez de 57 ms, e o custo fixo por conexão ficaria
  desprezível.
- **Com mais requisições por página.** Uma página com dezenas de recursos pequenos paga
  um handshake por recurso; quanto menor o recurso, maior a parte do tempo gasta
  esperando RTTs, e não transmitindo dados.
- **Com HTTPS.** Cada conexão nova também paga o handshake TLS: mais 1 RTT no TLS 1.3,
  ou 2 no TLS 1.2.
- **Com respostas maiores.** Toda conexão nova começa no *slow start*, com janela de
  congestionamento pequena; uma conexão persistente reaproveita a janela já aberta.

No extremo oposto, em localhost (RTT ≈ 0) a diferença quase desaparece. Por isso o
trabalho exige máquinas distintas: o ganho da conexão persistente é, antes de tudo, um
ganho de RTTs.
