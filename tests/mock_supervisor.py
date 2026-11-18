"""Test-only proxy originating from Supervisor's address on an isolated bridge."""

import http.client
import os
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

PREFIX = "/api/hassio_ingress/" + os.environ["TEST_INGRESS_PATH"]
ADMIN = os.environ["TEST_ADMIN"]
USER = os.environ["TEST_USER"]
HOP = {"connection", "transfer-encoding", "server", "date"}


class Ingress(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def forward(self):
        if self.path == "/":
            return self.respond(
                f'<iframe title="OpenSOHO" src="{PREFIX}/" style="width:100%;height:90vh;border:0" '
                '> </iframe>'
            )
        if not urlsplit(self.path).path.startswith(PREFIX + "/"):
            return self.respond("Not found", 404)
        cookie = SimpleCookie(self.headers.get("Cookie", "")).get("test_session")
        value = cookie.value if cookie else ""
        headers = {
            key: val
            for key, val in self.headers.items()
            if not key.lower().startswith("x-remote-user-")
            and key.lower() not in (HOP | {"host", "x-ingress-path"})
        }
        if value in (ADMIN, USER):
            headers["X-Remote-User-Id"] = "0123456789abcdef" * 2
            headers["X-Remote-User-Groups"] = (
                "system-users,system-admin" if value == ADMIN else "system-users"
            )
        headers["X-Ingress-Path"] = PREFIX
        length = int(self.headers.get("Content-Length", 0))
        with_connection = http.client.HTTPConnection("controller", 8091, timeout=75)
        try:
            with_connection.request(
                self.command, self.path[len(PREFIX):],
                body=self.rfile.read(length) if length else None, headers=headers,
            )
            response = with_connection.getresponse()
            is_sse = response.getheader("Content-Type", "").startswith("text/event-stream")
            self.send_response(response.status)
            for key, val in response.getheaders():
                if key.lower() not in (HOP | {"content-length"}):
                    self.send_header(key, val)
            if is_sse:
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while line := response.readline():
                    self.wfile.write(f"{len(line):x}\r\n".encode() + line + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            else:
                result = response.read()
                length = response.getheader("Content-Length") if self.command == "HEAD" else str(len(result))
                self.send_header("Content-Length", length or "0")
                self.end_headers()
                self.wfile.write(result)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with_connection.close()

    def respond(self, body, status=200):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_HEAD = do_POST = do_PATCH = do_PUT = do_DELETE = do_OPTIONS = forward


ThreadingHTTPServer(("0.0.0.0", 8000), Ingress).serve_forever()
