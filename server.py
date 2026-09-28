#!/usr/bin/env python3
"""Servidor HTTP/1.1 sobre sockets TCP - Laboratório de Redes, T1, Grupo 5.

Uso: python3 server.py --port 8080 --root ./www
"""

import argparse
import os
import socket
import sys
import threading
from datetime import datetime
from email.utils import formatdate

SERVER_NAME = "LabRedes-T1-Grupo5/1.0"
RECV_SIZE = 4096
MAX_HEADER_BYTES = 8192
FILE_CHUNK_SIZE = 64 * 1024
ALLOWED_METHODS = ("GET", "HEAD")
SUPPORTED_VERSIONS = ("HTTP/1.0", "HTTP/1.1")
HEX_DIGITS = b"0123456789abcdefABCDEF"

REASONS = {
    200: "OK",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
}

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}
DEFAULT_MIME_TYPE = "application/octet-stream"

log_lock = threading.Lock()
quiet = False


class BadRequest(Exception):
    """Requisição malformada: responde 400 e fecha a conexão."""


class Request:
    def __init__(self, method, target, version, headers):
        self.method = method
        self.target = target
        self.version = version
        self.headers = headers  # nomes em minúsculas -> valor


def log(conn_id, message):
    if quiet:
        return
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    thread_name = threading.current_thread().name
    with log_lock:
        print(f"{timestamp} [conn {conn_id} | {thread_name}] {message}", flush=True)


# ---------------------------------------------------------------- parsing

def parse_request(head):
    """Interpreta a request line e as linhas de cabeçalho (bytes, sem o CRLF CRLF final)."""
    lines = head.split(b"\r\n")
    try:
        request_line = lines[0].decode("ascii")
    except UnicodeDecodeError:
        raise BadRequest("request line com bytes não ASCII")

    # request-line = método SP request-target SP versão (exatamente dois espaços)
    parts = request_line.split(" ")
    if len(parts) != 3 or not all(parts):
        raise BadRequest(f"request line inválida: {request_line!r}")
    method, target, version = parts
    if version not in SUPPORTED_VERSIONS:
        raise BadRequest(f"versão não suportada: {version!r}")

    headers = {}
    for line in lines[1:]:
        if b":" not in line:
            raise BadRequest(f"cabeçalho sem ':': {line!r}")
        name, value = line.split(b":", 1)
        name = name.decode("ascii", errors="replace")
        # a RFC 9112 proíbe espaço entre o nome do campo e o ':'
        if not name or name != name.strip():
            raise BadRequest(f"nome de cabeçalho inválido: {name!r}")
        name = name.lower()
        value = value.decode("latin-1").strip()
        # cabeçalhos repetidos são combinados em lista separada por vírgula
        headers[name] = f"{headers[name]}, {value}" if name in headers else value

    return Request(method, target, version, headers)


def body_length(request):
    """Tamanho do corpo que vem após o cabeçalho, para descartá-lo do fluxo."""
    if "transfer-encoding" in request.headers:
        # sem suporte a corpo chunked: não daria para saber onde a próxima requisição começa
        raise BadRequest("Transfer-Encoding em requisição não é suportado")
    value = request.headers.get("content-length", "0")
    if not value.isdigit():
        raise BadRequest(f"Content-Length inválido: {value!r}")
    return int(value)


def wants_keep_alive(request):
    tokens = [t.strip().lower() for t in request.headers.get("connection", "").split(",")]
    if "close" in tokens:
        return False
    if request.version == "HTTP/1.0":
        # no HTTP/1.0 a conexão só persiste se o cliente pedir explicitamente
        return "keep-alive" in tokens
    return True  # HTTP/1.1: persistente por padrão


def percent_decode(path):
    """Decodifica %XX em bytes. Feito à mão para não depender de biblioteca de HTTP/URL."""
    raw = path.encode("ascii")
    decoded = bytearray()
    i = 0
    while i < len(raw):
        if raw[i] == ord("%"):
            hex_pair = raw[i + 1:i + 3]
            if len(hex_pair) != 2 or any(c not in HEX_DIGITS for c in hex_pair):
                raise BadRequest(f"percent-encoding inválido em {path!r}")
            decoded.append(int(hex_pair, 16))
            i += 3
        else:
            decoded.append(raw[i])
            i += 1
    return bytes(decoded)


# ------------------------------------------------------ resolução de caminho

def resolve_path(target, root):
    """Converte o request-target em um caminho de arquivo dentro de root.

    Retorna (status, caminho). status é 200 quando o arquivo existe, 403 quando
    o caminho escapa do root e 404 quando o arquivo não existe.
    """
    # absolute-form (http://host/caminho): fica só com o caminho
    if target.lower().startswith(("http://", "https://")):
        authority_and_path = target.split("//", 1)[1]
        target = "/" + authority_and_path.split("/", 1)[1] if "/" in authority_and_path else "/"
    if not target.startswith("/"):
        raise BadRequest(f"request-target inválido: {target!r}")

    path = target.split("?", 1)[0].split("#", 1)[0]
    # decodifica ANTES de validar: %2e%2e vira '..' e precisa ser pego pela checagem abaixo
    decoded = percent_decode(path)
    if b"\x00" in decoded:
        raise BadRequest("byte nulo no caminho")
    try:
        relative = decoded.decode("utf-8").lstrip("/")
    except UnicodeDecodeError:
        raise BadRequest("caminho não é UTF-8 válido")

    candidate = os.path.join(root, relative)
    if os.path.isdir(candidate):
        candidate = os.path.join(candidate, "index.html")

    # realpath resolve '..' e links simbólicos; só então comparamos com o root.
    # commonpath compara componentes inteiros: '/www2' não passa como se estivesse em '/www'.
    full_path = os.path.realpath(candidate)
    try:
        inside_root = os.path.commonpath([root, full_path]) == root
    except ValueError:
        # Windows: outro drive (/D:/x) ou nome reservado (/CON vira \\.\CON)
        inside_root = False
    if not inside_root:
        return 403, None
    if not os.path.isfile(full_path):
        return 404, None
    return 200, full_path


# --------------------------------------------------------------- respostas

def build_head(status, content_type, content_length, keep_alive, request_version, extra_headers=()):
    lines = [
        f"HTTP/1.1 {status} {REASONS[status]}",
        f"Date: {formatdate(usegmt=True)}",  # IMF-fixdate: 'Sun, 06 Nov 1994 08:49:37 GMT'
        f"Server: {SERVER_NAME}",
        f"Content-Type: {content_type}",
        f"Content-Length: {content_length}",
    ]
    lines.extend(f"{name}: {value}" for name, value in extra_headers)
    if not keep_alive:
        lines.append("Connection: close")
    elif request_version == "HTTP/1.0":
        lines.append("Connection: keep-alive")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")


def error_body(status):
    title = f"{status} {REASONS[status]}"
    return (f"<!DOCTYPE html>\n<html><head><title>{title}</title></head>"
            f"<body><h1>{title}</h1><p>{SERVER_NAME}</p></body></html>\n").encode("utf-8")


def send_error(conn, status, keep_alive, request=None, extra_headers=()):
    """Envia uma resposta de erro. Retorna o número de bytes de corpo enviados."""
    body = error_body(status)
    version = request.version if request else "HTTP/1.1"
    head = build_head(status, MIME_TYPES[".html"], len(body), keep_alive, version, extra_headers)
    if request is not None and request.method == "HEAD":
        conn.sendall(head)
        return 0
    conn.sendall(head + body)
    return len(body)


def send_file(conn, request, file_path, keep_alive):
    """Envia 200 com o arquivo. Para HEAD, só o cabeçalho (com o Content-Length do GET)."""
    extension = os.path.splitext(file_path)[1].lower()
    content_type = MIME_TYPES.get(extension, DEFAULT_MIME_TYPE)
    size = os.path.getsize(file_path)
    head = build_head(200, content_type, size, keep_alive, request.version)
    if request.method == "HEAD":
        conn.sendall(head)
        return 0
    sent = 0
    with open(file_path, "rb") as f:
        # cabeçalho vai junto com o primeiro bloco: dois send() pequenos seguidos
        # fariam o segundo esperar o ACK do primeiro (Nagle + ACK atrasado do cliente)
        chunk = f.read(FILE_CHUNK_SIZE)
        conn.sendall(head + chunk)
        sent += len(chunk)
        # demais blocos de 64 KB: arquivos grandes não precisam caber na memória
        while True:
            chunk = f.read(FILE_CHUNK_SIZE)
            if not chunk:
                break
            conn.sendall(chunk)
            sent += len(chunk)
    return sent


def handle_request(conn, request, root, keep_alive):
    """Responde uma requisição já interpretada. Retorna (status, bytes de corpo)."""
    if request.method not in ALLOWED_METHODS:
        sent = send_error(conn, 405, keep_alive, request, [("Allow", ", ".join(ALLOWED_METHODS))])
        return 405, sent

    status, file_path = resolve_path(request.target, root)
    if status != 200:
        return status, send_error(conn, status, keep_alive, request)
    try:
        return 200, send_file(conn, request, file_path, keep_alive)
    except PermissionError:
        return 403, send_error(conn, 403, keep_alive, request)


# ---------------------------------------------------------------- conexões

def format_address(address):
    """'ip:porta' para IPv4 e '[ip]:porta' para IPv6 (address vem do accept)."""
    ip, port = address[0], address[1]
    if ip.startswith("::ffff:"):  # cliente IPv4 num socket IPv6 dual-stack
        ip = ip[len("::ffff:"):]
    return f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"


def handle_connection(conn, address, conn_id, root, timeout):
    client = format_address(address)
    log(conn_id, f"conexão aberta de {client}")
    # o mesmo timeout vale para esperar a próxima requisição (conexão ociosa)
    # e para uma requisição que chega pela metade (cliente lento)
    conn.settimeout(timeout)
    buffer = b""
    requests_served = 0
    reason = "EOF do cliente"
    try:
        while True:
            # O TCP entrega um fluxo de bytes: um recv() pode trazer meia requisição,
            # uma inteira ou uma e o começo da próxima. Acumulamos até a linha vazia.
            buffer = buffer.lstrip(b"\r\n")  # RFC 9112: ignorar CRLF antes da request line
            while b"\r\n\r\n" not in buffer:
                if len(buffer) > MAX_HEADER_BYTES:
                    raise BadRequest("cabeçalho maior que o limite")
                data = conn.recv(RECV_SIZE)
                if not data:
                    return  # cliente fechou (reason = EOF)
                buffer += data
                buffer = buffer.lstrip(b"\r\n")

            head, buffer = buffer.split(b"\r\n\r\n", 1)  # o que sobra fica para a próxima
            if len(head) > MAX_HEADER_BYTES:
                raise BadRequest("cabeçalho maior que o limite")
            request = parse_request(head)

            # descarta um eventual corpo para não confundi-lo com a próxima requisição
            remaining = body_length(request)
            while len(buffer) < remaining:
                data = conn.recv(RECV_SIZE)
                if not data:
                    return
                buffer += data
            buffer = buffer[remaining:]

            keep_alive = wants_keep_alive(request)
            status, sent = handle_request(conn, request, root, keep_alive)
            requests_served += 1
            log(conn_id, f'"{request.method} {request.target} {request.version}" {status} {sent}B')
            if not keep_alive:
                reason = "Connection: close"
                return
    except BadRequest as error:
        reason = f"400 ({error})"
        log(conn_id, f"400 Bad Request: {error}")
        try:
            send_error(conn, 400, keep_alive=False)
        except OSError:
            pass
    except socket.timeout:
        reason = f"timeout de {timeout:g}s"
    except OSError as error:  # ECONNRESET, EPIPE etc.
        reason = f"erro de socket ({error.__class__.__name__})"
    finally:
        conn.close()
        log(conn_id, f"conexão fechada com {client}: {reason}, {requests_served} requisição(ões)")


def parse_args():
    parser = argparse.ArgumentParser(description="Servidor HTTP/1.1 sobre sockets TCP (T1 - Grupo 5)")
    parser.add_argument("--port", type=int, required=True, help="porta TCP (use > 1024)")
    parser.add_argument("--root", required=True, help="diretório raiz servido")
    parser.add_argument("--host", default="0.0.0.0", help="endereço de bind (padrão: 0.0.0.0; '::' = IPv6 e IPv4)")
    parser.add_argument("--timeout", type=float, default=5.0, help="timeout de conexão ociosa em s (padrão: 5)")
    parser.add_argument("--quiet", action="store_true", help="não imprime o log de requisições")
    return parser.parse_args()


def main():
    global quiet
    args = parse_args()
    quiet = args.quiet
    root = os.path.realpath(args.root)
    if not os.path.isdir(root):
        sys.exit(f"erro: diretório raiz não existe: {args.root}")

    if ":" in args.host:
        # IPv6 (ex.: hotspot só IPv6). Com IPV6_V6ONLY desligado o mesmo socket
        # também aceita clientes IPv4, que aparecem como ::ffff:a.b.c.d
        server = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        server.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    else:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # permite reiniciar o servidor sem esperar o TIME_WAIT da execução anterior
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(128)
    print(f"{SERVER_NAME} escutando em {format_address((args.host, args.port))}, raiz {root}, "
          f"timeout {args.timeout:g}s", flush=True)

    conn_id = 0
    try:
        while True:
            conn, address = server.accept()
            conn_id += 1
            # uma thread por conexão: uma conexão lenta bloqueia só a própria thread
            thread = threading.Thread(
                target=handle_connection,
                args=(conn, address, conn_id, root, args.timeout),
                name=f"t{conn_id}",
                daemon=True,
            )
            thread.start()
    except KeyboardInterrupt:
        print("\nencerrando", flush=True)
    finally:
        server.close()


if __name__ == "__main__":
    main()
