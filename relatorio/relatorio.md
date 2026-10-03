---
title: "T1 – Servidor HTTP/1.1 sobre sockets TCP"
subtitle: "Laboratório de Redes de Computadores – Grupo 5"
author: "<Integrante 1>, <Integrante 2>, <Integrante 3>"
date: "<data>"
---

<!--
RASCUNHO. Tudo entre <...> ou marcado com TODO precisa ser preenchido com os
dados reais das medições ENTRE MÁQUINAS DISTINTAS. As análises dos itens 8–10
devem ser escritas pelo grupo: os roteiros abaixo são só guias.
Exportar para PDF: abrir no VS Code/Typora e exportar, ou
  pandoc relatorio.md -o relatorio.pdf
-->

# 1. Arquitetura

**Ambiente.** Servidor no notebook `<macOS: modelo, versão, IP 192.168.15.9>`; cliente no
notebook `<Ubuntu: modelo, versão, IP 192.168.15.x>`; os dois na Wi-Fi doméstica
(`<roteador/banda: 2,4 ou 5 GHz>`), em IPv4. Segundo cliente para o teste de
simultaneidade: `<celular na mesma Wi-Fi, IP …>`. Servidor escutando em `0.0.0.0:8080`,
raiz `./www`.

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

TODO (opcional): print do terminal com as respostas.

# 4. Captura de uma transação completa

Captura `capturas/transacao.pcapng`: `curl http://192.168.15.9:8080/index.html`
feito do Ubuntu (192.168.15.15) e capturado no Mac (192.168.15.9), filtro
`tcp.port == 8080`. Uma única conexão, 12 pacotes, 19 ms do SYN ao último ACK.

TODO: print do Wireshark (`relatorio/img/transacao.png`).

| Pacote | Origem → destino | Flags | Dados | Papel |
|---|---|---|---|---|
| 1 | Ubuntu → Mac | SYN | 0 | **Handshake** (1/3), MSS 1460 |
| 2 | Mac → Ubuntu | SYN, ACK | 0 | **Handshake** (2/3) |
| 3 | Ubuntu → Mac | ACK | 0 | **Handshake** (3/3), 6,1 ms após o SYN ≈ 1 RTT |
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

TODO (opcional): print da janela Conversations.

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

TODO: comentar a diferença entre o RTT do ping e o dos handshakes.

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

Dados de `c1.pcapng`:

- Um handshake = 3 pacotes: SYN (74 B) + SYN-ACK (78 B) + ACK (66 B) = **218 B**.
- Um encerramento = 4 pacotes: FIN, ACK, FIN, ACK (66 B cada) = **264 B**.
- Abrir e fechar uma conexão: **7 pacotes, 482 B**. Em C2 (1 conexão), exatamente isso.
- `metricas.py` em C1: abertura 30 pacotes / 2 180 B; encerramento 62 pacotes / 4 092 B
  (inclui ACKs puros de dados que chegam depois do primeiro FIN).
- Diferença de payload C1 − C2 = 380 B = 10 × (`Connection: close\r\n` na
  requisição + na resposta) = 10 × 2 × 19 B.

TODO: escrever a análise.

Roteiro:

- Quantos pacotes e bytes há em **um** handshake (SYN, SYN-ACK, ACK)? E em um
  encerramento (FIN, ACK, FIN, ACK)? Conferir num stream do Wireshark.
- Multiplicar por 10 conexões e comparar com o total de C1 (em %).
- Comparar com a diferença de pacotes e de bytes entre C1 e C2: quanto dela é
  explicado só pela abertura e pelo fechamento de conexões?
- Detalhe: o script conta como encerramento todo FIN/RST e todo ACK puro depois
  do primeiro FIN da conexão.

# 9. Análise em função do RTT

Dados (rodada 1):

- T_C1 − T_C2 = 136,1 − 65,3 = **70,8 ms**.
- Em RTTs: 70,8 / 7,09 (mediana do ping) ≈ **10 RTT**; 70,8 / 5,2 (RTT dos
  handshakes na captura) ≈ 13,6 RTT. Esperado: 9 RTT (9 handshakes a mais).
- Em C1, visto do servidor, cada requisição gasta: SYN → GET ≈ **5,4 ms** (1 RTT
  de handshake) + GET → fim da resposta ≈ 0,8 ms + fim da resposta → próximo SYN
  ≈ **6,4 ms** (1 RTT: a resposta chega ao cliente e o SYN seguinte volta).
- Em C2, o intervalo entre GETs consecutivos é ≈ **4,8 ms** (1 RTT por requisição).
- Conta: C1 ≈ 10 × (5,4 + 0,8 + 6,4) ≈ 126 ms (medido: 136 ms);
  C2 ≈ 6,4 (handshake) + 9 × 4,8 ≈ 50 ms + encerramento (medido: 65 ms).

TODO: escrever a análise.

Roteiro:

- Em C1, cada requisição precisa de 1 RTT de handshake antes de poder enviar o
  GET, mais 1 RTT de requisição/resposta. Em C2 o handshake acontece uma vez só.
- Diferença esperada ≈ 9 × RTT (9 handshakes a mais). Calcular
  (T_C1 − T_C2) / RTT_médio e comparar com 9.
- C1 e C2 usam um único processo `curl`, então a diferença de tempo vem só da
  rede e das conexões. Numa medição anterior, com um `curl` por requisição, cada
  processo novo somava ~150 ms entre uma conexão e a seguinte no Windows, muito
  mais que o RTT. Vale citar como armadilha de medição. Olhar no Wireshark o intervalo entre o SYN
  e o GET de cada conexão, que deve ser ≈ 1 RTT.
- O encerramento (FIN) em geral não soma RTT ao tempo percebido: o cliente
  já recebeu a resposta completa quando a troca de FINs termina.

# 10. Conclusão

TODO: escrever.

Roteiro: o custo extra de C1 é ≈ (número de conexões novas) × RTT. A persistência
ganha mais quanto **maior o RTT** (ex.: servidor em outro continente, rede
móvel/satélite) e quanto **mais requisições** a página faz (muitos recursos
pequenos, onde o tempo de transmissão é pequeno perto do RTT). Em localhost
(RTT ≈ 0) a diferença quase some, por isso o trabalho exige máquinas distintas.
