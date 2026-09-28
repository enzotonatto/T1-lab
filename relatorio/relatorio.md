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

**Ambiente.** Servidor em `<máquina A: modelo, macOS x, IP 192.168.x.x>`, clientes em
`<máquina B: …, IP …>` e `<máquina C: …>`, todas na rede `<Wi-Fi doméstica / hotspot / …>`.
Rede: hotspot de iPhone (`<operadora>`), que fornece **somente IPv6**. O servidor
foi executado com `--host ::`: socket `AF_INET6` com `IPV6_V6ONLY` desligado, que
aceita clientes IPv6 e IPv4 (estes aparecem como `::ffff:a.b.c.d`). O padrão
continua sendo `0.0.0.0`, como pede o enunciado. Raiz `./www`, porta 8080.
TODO: ajustar se as medições finais forem feitas em rede IPv4.

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

Gerada com `scripts/conformidade.sh <ip>` executado na máquina `<B>`.

| Status | Requisição (`curl`) | Resposta obtida (linha de status e cabeçalhos relevantes) |
|---|---|---|
| 200 | `curl -i http://<ip>:8080/index.html` | TODO: colar `HTTP/1.1 200 OK`, `Content-Type`, `Content-Length`, `Date`, `Server` |
| 200 (HEAD) | `curl -I http://<ip>:8080/index.html` | TODO: mesmos cabeçalhos, sem corpo |
| 400 | `curl -i --request-target "/index.html extra" http://<ip>:8080/` | TODO |
| 400 | `curl -i -H $'X-Ok: 1\r\nCabecalhoSemDoisPontos' http://<ip>:8080/` | TODO |
| 403 | `curl -i --path-as-is http://<ip>:8080/../../etc/passwd` | TODO |
| 404 | `curl -i http://<ip>:8080/nao-existe.html` | TODO |
| 405 | `curl -i -X POST -d "a=1" http://<ip>:8080/index.html` | TODO: incluir `Allow: GET, HEAD` |

# 3. Demonstração de segurança (travessia de diretório)

Gerada com `scripts/travessia.sh <ip>`. `--path-as-is` impede o `curl` de
normalizar o `..` antes de enviar.

| # | Requisição enviada | Técnica | Resposta |
|---|---|---|---|
| 1 | `GET /../../etc/passwd` | `..` literal | TODO `403 Forbidden` |
| 2 | `GET /%2e%2e/%2e%2e/etc/passwd` | `.` codificado | TODO |
| 3 | `GET /..%2f..%2f..%2fetc%2fpasswd` | `/` codificado | TODO |
| 4 | `GET /img/../../../etc/passwd` | sai do root a partir de um subdiretório | TODO |
| 5 | `GET /%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd` | tudo codificado | TODO |

Por que funciona: o caminho é **decodificado antes** da verificação (então
`%2e%2e` vira `..`), e a verificação é feita sobre o caminho **canônico**
(`realpath` resolve `..` e links simbólicos), comparando componentes inteiros
com `commonpath` (`/www2` não passa como se estivesse dentro de `/www`). Os
testes automatizados também cobrem um link simbólico dentro de `www/` apontando
para fora (403).

TODO: print do terminal com as respostas e/ou do log do servidor.

# 4. Captura de uma transação completa

Captura `capturas/transacao.pcapng`: `curl http://<ip>:8080/index.html` feito da
máquina `<B>` e capturado na máquina `<A>`, filtro `tcp.port == 8080`.

TODO: print do Wireshark, identificando:

| Pacotes (nº) | Papel |
|---|---|
| TODO | Handshake: SYN (B→A), SYN-ACK (A→B), ACK (B→A) |
| TODO | Requisição: segmento PSH/ACK com `GET /index.html HTTP/1.1` |
| TODO | Resposta: segmento(s) com `HTTP/1.1 200 OK` + corpo, e os ACKs |
| TODO | Encerramento: FIN/ACK de cada lado e ACKs finais |

# 5. Evidência de atendimento simultâneo

Máquinas `<B>` e `<C>` executando `scripts/simultaneo.sh <ip>` ao mesmo tempo.
Cada uma deixa uma requisição pela metade aberta e, enquanto isso, faz
requisições normais, que são atendidas.

TODO: trecho do log do servidor mostrando conexões de dois IPs diferentes
intercaladas (ids de conexão e threads distintos, horários sobrepostos).

Observação do teste com navegador: ao carregar `index.html`, o navegador abriu
3 conexões em paralelo e reaproveitou uma delas para 4 requisições. O servidor
fechou as três por timeout ocioso depois de 5 s (TODO: log real entre máquinas).

# 6. RTT medido

`ping -c 20 <ip-servidor>` a partir de `<B>`:

TODO: `round-trip min/avg/max/stddev = … / … / … / … ms`. **RTT médio = <x> ms.**

# 7. Comparação C1 × C2

10 requisições sequenciais a `/medicao.html` (4 636 bytes de corpo).
C1: `scripts/c1.sh` (uma conexão por requisição, `Connection: close`).
C2: `scripts/c2.sh` (um processo `curl`, uma conexão persistente).
Métricas extraídas com `scripts/metricas.py` (mediana de 3 execuções).

| Métrica | C1 | C2 | Economia de C2 |
|---|---|---|---|
| Handshakes TCP completos | TODO (esperado 10) | TODO (esperado 1) | – |
| Total de pacotes | TODO | TODO | TODO % |
| Bytes totais | TODO | TODO | TODO % |
| Tempo total | TODO ms | TODO ms | TODO % |

Economia % = (C1 − C2) / C1 × 100.

# 8. Overhead de conexão (C1)

TODO: escrever a partir da saída de `metricas.py` para `c1.pcapng` e conferir no Wireshark.

Roteiro:

- Quantos pacotes e bytes há em **um** handshake (SYN, SYN-ACK, ACK)? E em um
  encerramento (FIN, ACK, FIN, ACK)? Conferir num stream do Wireshark.
- Multiplicar por 10 conexões e comparar com o total de C1 (em %).
- Comparar com a diferença de pacotes e de bytes entre C1 e C2: quanto dela é
  explicado só pela abertura e pelo fechamento de conexões?
- IPv6: o cabeçalho IP tem 40 bytes (IPv4: 20). Quanto isso pesa num SYN
  (sem payload) e no total de bytes de overhead?
- Detalhe: o script conta como encerramento todo FIN/RST e todo ACK puro depois
  do primeiro FIN da conexão.

# 9. Análise em função do RTT

TODO: escrever com os números reais.

Roteiro:

- Em C1, cada requisição precisa de 1 RTT de handshake antes de poder enviar o
  GET, mais 1 RTT de requisição/resposta. Em C2 o handshake acontece uma vez só.
- Diferença esperada ≈ 9 × RTT (9 handshakes a mais). Calcular
  (T_C1 − T_C2) / RTT_médio e comparar com 9.
- Se a diferença medida for maior que 9 RTT, explicar de onde vem o resto
  (ex.: C1 inicia um processo `curl` por requisição, e esse tempo aparece entre
  o fim de uma conexão e o SYN da seguinte). Olhar no Wireshark o intervalo entre o SYN
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
