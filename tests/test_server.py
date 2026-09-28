"""Testes do servidor, via sockets crus contra uma instância em localhost.

Rodar a partir da raiz do projeto:  python3 -m unittest -v
(localhost só para desenvolvimento; as medições do relatório são entre máquinas)
"""

import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(PROJECT_DIR, "server.py")
TIMEOUT = 1.0  # timeout ocioso curto para os testes rodarem rápido
IMF_FIXDATE = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{2} "
                         r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4} "
                         r"\d{2}:\d{2}:\d{2} GMT$")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Client:
    """Socket cliente com buffer próprio: respostas que chegam juntas não se perdem."""

    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.buffer = b""

    def sendall(self, data):
        self.sock.sendall(data)

    def _fill(self):
        chunk = self.sock.recv(4096)
        if not chunk:
            raise ConnectionError(f"conexão fechada; buffer: {self.buffer!r}")
        self.buffer += chunk

    def read_response(self, head_only=False):
        """Lê uma resposta completa: (status, headers, body)."""
        while b"\r\n\r\n" not in self.buffer:
            self._fill()
        head, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        version, status, _ = lines[0].split(" ", 2)
        assert version == "HTTP/1.1", lines[0]
        headers = {}
        for line in lines[1:]:
            name, value = line.split(":", 1)
            headers[name.lower()] = value.strip()
        length = 0 if head_only else int(headers["content-length"])
        while len(self.buffer) < length:
            self._fill()
        body, self.buffer = self.buffer[:length], self.buffer[length:]
        return int(status), headers, body

    def close(self):
        self.sock.close()


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = os.path.join(cls.tmp, "www")
        os.makedirs(os.path.join(cls.root, "sub"))
        os.makedirs(os.path.join(cls.tmp, "www2"))  # vizinho com prefixo parecido
        files = {
            "index.html": b"<h1>index</h1>",
            "sub/index.html": b"<h1>sub</h1>",
            "a.css": b"body{}", "a.js": b"1;", "a.json": b"{}", "a.txt": b"txt",
            "a.png": b"png", "a.jpg": b"jpg", "a.pdf": b"pdf", "a.xyz": b"xyz",
            "com espaco.txt": b"espaco",
            "grande.bin": os.urandom(300 * 1024),
        }
        for name, content in files.items():
            with open(os.path.join(cls.root, name), "wb") as f:
                f.write(content)
        with open(os.path.join(cls.tmp, "segredo.txt"), "wb") as f:
            f.write(b"segredo")
        with open(os.path.join(cls.tmp, "www2", "x.txt"), "wb") as f:
            f.write(b"vizinho")
        os.symlink(os.path.join(cls.tmp, "segredo.txt"), os.path.join(cls.root, "link-fora"))

        cls.port = free_port()
        cls.proc = subprocess.Popen(
            [sys.executable, SERVER, "--port", str(cls.port), "--root", cls.root,
             "--host", "127.0.0.1", "--timeout", str(TIMEOUT), "--quiet"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait()
        cls.proc.stderr.close()
        shutil.rmtree(cls.tmp)

    def connect(self):
        client = Client(self.port)
        self.addCleanup(client.close)
        return client

    def request(self, raw, head_only=False):
        client = self.connect()
        client.sendall(raw)
        return client.read_response(head_only)

    def get(self, target, method="GET", extra=""):
        raw = f"{method} {target} HTTP/1.1\r\nHost: x\r\n{extra}\r\n".encode()
        return self.request(raw, head_only=(method == "HEAD"))

    def assert_closed(self, client):
        client.sock.settimeout(TIMEOUT + 2)
        self.assertEqual(client.buffer + client.sock.recv(1), b"")

    # ---------------------------------------------------------- respostas

    def test_get_200_with_mandatory_headers(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"<h1>index</h1>")
        self.assertEqual(headers["content-length"], str(len(body)))
        self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
        self.assertRegex(headers["date"], IMF_FIXDATE)
        self.assertEqual(headers["server"], "LabRedes-T1-Grupo5/1.0")

    def test_head_same_headers_without_body(self):
        _, get_headers, get_body = self.get("/a.txt")
        sock = self.connect()
        sock.sendall(b"HEAD /a.txt HTTP/1.1\r\nHost: x\r\n\r\n")
        status, head_headers, _ = sock.read_response(head_only=True)
        self.assertEqual(status, 200)
        get_headers.pop("date"), head_headers.pop("date")
        self.assertEqual(get_headers, head_headers)
        self.assertEqual(head_headers["content-length"], str(len(get_body)))
        # nada de corpo: a próxima coisa no fluxo é a resposta seguinte
        sock.sendall(b"GET /a.txt HTTP/1.1\r\nHost: x\r\n\r\n")
        status, _, body = sock.read_response()
        self.assertEqual((status, body), (200, b"txt"))

    def test_content_types(self):
        expected = {
            "/a.css": "text/css", "/a.js": "text/javascript", "/a.json": "application/json",
            "/a.txt": "text/plain", "/a.png": "image/png", "/a.jpg": "image/jpeg",
            "/a.pdf": "application/pdf", "/a.xyz": "application/octet-stream",
        }
        for target, mime in expected.items():
            with self.subTest(target=target):
                _, headers, _ = self.get(target)
                self.assertEqual(headers["content-type"].split(";")[0], mime)

    def test_directory_serves_index(self):
        for target in ("/sub/", "/sub"):
            with self.subTest(target=target):
                status, _, body = self.get(target)
                self.assertEqual((status, body), (200, b"<h1>sub</h1>"))

    def test_percent_encoding_and_query(self):
        status, _, body = self.get("/com%20espaco.txt?x=1")
        self.assertEqual((status, body), (200, b"espaco"))

    def test_large_file(self):
        status, _, body = self.get("/grande.bin")
        self.assertEqual(status, 200)
        with open(os.path.join(self.root, "grande.bin"), "rb") as f:
            self.assertEqual(body, f.read())

    def test_404(self):
        status, headers, body = self.get("/nao-existe.html")
        self.assertEqual(status, 404)
        self.assertEqual(headers["content-length"], str(len(body)))
        self.assertGreater(len(body), 0)

    def test_404_head_has_length_without_body(self):
        status, headers, _ = self.get("/nao-existe.html", method="HEAD")
        self.assertEqual(status, 404)
        self.assertGreater(int(headers["content-length"]), 0)

    def test_405(self):
        for method in ("POST", "DELETE", "PUT", "OPTIONS"):
            with self.subTest(method=method):
                status, headers, body = self.get("/", method=method)
                self.assertEqual(status, 405)
                self.assertEqual(headers["allow"], "GET, HEAD")
                self.assertEqual(headers["content-length"], str(len(body)))

    def test_405_body_is_discarded_and_connection_kept(self):
        sock = self.connect()
        sock.sendall(b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 5\r\n\r\nabcde"
                     b"GET /a.txt HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertEqual(sock.read_response()[0], 405)
        status, _, body = sock.read_response()
        self.assertEqual((status, body), (200, b"txt"))

    def test_400_cases(self):
        cases = [
            b"GARBAGE\r\n\r\n",
            b"GET /\r\n\r\n",
            b"GET / HTTP/1.1 extra\r\n\r\n",
            b"GET  / HTTP/1.1\r\n\r\n",
            b"GET / HTTP/2.0\r\n\r\n",
            b"GET / HTTP/1.1\r\nSemDoisPontos\r\n\r\n",
            b"GET / HTTP/1.1\r\nHost : x\r\n\r\n",
            b"GET /%zz HTTP/1.1\r\n\r\n",
            b"GET /a%00.txt HTTP/1.1\r\n\r\n",
            b"GET a.txt HTTP/1.1\r\n\r\n",
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                sock = self.connect()
                sock.sendall(raw)
                status, headers, _ = sock.read_response()
                self.assertEqual(status, 400)
                self.assertEqual(headers["connection"], "close")
                self.assert_closed(sock)

    def test_header_too_large(self):
        sock = self.connect()
        sock.sendall(b"GET / HTTP/1.1\r\nX: " + b"a" * 10000 + b"\r\n\r\n")
        self.assertEqual(sock.read_response()[0], 400)

    # ---------------------------------------------------------- travessia

    def test_traversal_403(self):
        for target in ("/../segredo.txt", "/../../../../etc/passwd",
                       "/%2e%2e/segredo.txt", "/%2E%2E%2Fsegredo.txt", "/..%2fsegredo.txt",
                       "/sub/../../segredo.txt", "/../www2/x.txt", "/link-fora",
                       "//etc/../../segredo.txt"):
            with self.subTest(target=target):
                status, _, body = self.get(target)
                self.assertEqual(status, 403)
                self.assertNotIn(b"segredo", body)
                self.assertNotIn(b"vizinho", body)

    def test_dotdot_inside_root_is_allowed(self):
        status, _, body = self.get("/sub/../a.txt")
        self.assertEqual((status, body), (200, b"txt"))

    # ---------------------------------------------------- fluxo de bytes

    def test_request_split_across_many_sends(self):
        sock = self.connect()
        for byte in b"GET /a.txt HTTP/1.1\r\nHost: x\r\n\r\n":
            sock.sendall(bytes([byte]))
            time.sleep(0.002)
        status, _, body = sock.read_response()
        self.assertEqual((status, body), (200, b"txt"))

    def test_pipelined_requests_in_one_send(self):
        sock = self.connect()
        sock.sendall(b"GET /a.txt HTTP/1.1\r\nHost: x\r\n\r\n"
                     b"GET /a.css HTTP/1.1\r\nHost: x\r\n\r\n"
                     b"GET /a.json HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        bodies = [sock.read_response()[2] for _ in range(3)]
        self.assertEqual(bodies, [b"txt", b"body{}", b"{}"])
        self.assert_closed(sock)

    # ------------------------------------------------------- persistência

    def test_keep_alive_multiple_requests(self):
        sock = self.connect()
        for _ in range(5):
            sock.sendall(b"GET /a.txt HTTP/1.1\r\nHost: x\r\n\r\n")
            status, headers, body = sock.read_response()
            self.assertEqual((status, body), (200, b"txt"))
            self.assertNotIn("connection", headers)

    def test_connection_close(self):
        sock = self.connect()
        sock.sendall(b"GET /a.txt HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        status, headers, _ = sock.read_response()
        self.assertEqual(status, 200)
        self.assertEqual(headers["connection"], "close")
        self.assert_closed(sock)

    def test_http10_closes_by_default(self):
        sock = self.connect()
        sock.sendall(b"GET /a.txt HTTP/1.0\r\n\r\n")
        _, headers, _ = sock.read_response()
        self.assertEqual(headers["connection"], "close")
        self.assert_closed(sock)

    def test_http10_keep_alive(self):
        sock = self.connect()
        sock.sendall(b"GET /a.txt HTTP/1.0\r\nConnection: keep-alive\r\n\r\n")
        _, headers, _ = sock.read_response()
        self.assertEqual(headers["connection"], "keep-alive")
        sock.sendall(b"GET /a.txt HTTP/1.0\r\n\r\n")
        self.assertEqual(sock.read_response()[0], 200)

    def test_idle_timeout(self):
        sock = self.connect()
        sock.sendall(b"GET /a.txt HTTP/1.1\r\nHost: x\r\n\r\n")
        sock.read_response()
        start = time.monotonic()
        self.assert_closed(sock)
        self.assertAlmostEqual(time.monotonic() - start, TIMEOUT, delta=0.5)

    # -------------------------------------------------------- concorrência

    def test_slow_client_does_not_block_others(self):
        slow = self.connect()
        slow.sendall(b"GET /a.txt HTTP/1.1\r\n")  # requisição pela metade
        start = time.monotonic()
        status, _, _ = self.get("/a.txt")
        self.assertEqual(status, 200)
        self.assertLess(time.monotonic() - start, 0.5)
        slow.sendall(b"Host: x\r\n\r\n")
        self.assertEqual(slow.read_response()[0], 200)


if __name__ == "__main__":
    unittest.main()
