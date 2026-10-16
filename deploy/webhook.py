"""Deploy receiver: accepts a signed release tarball from GitHub Actions and runs deploy.sh.

Listens on 127.0.0.1 only; Caddy forwards https://<domain>/__deploy here.
The request body is a .tar.gz of the repo; header X-Signature must be
"sha256=" + HMAC-SHA256(DEPLOY_SECRET, body). Uses only the standard library. Same receiver the standalone price checker used.
"""
import hashlib
import hmac
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SECRET = os.environ["DEPLOY_SECRET"].encode()
PORT = int(os.environ.get("DEPLOY_PORT", "9002"))
MAX_BODY = 50 * 1024 * 1024
DEPLOY_SH = Path(__file__).resolve().parent / "deploy.sh"
_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, text: str) -> None:
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/__deploy":
            return self._reply(404, "not found\n")
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BODY:
            return self._reply(413, "bad body size\n")
        body = self.rfile.read(length)
        expected = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, self.headers.get("X-Signature", "")):
            return self._reply(403, "bad signature\n")
        if not _lock.acquire(blocking=False):
            return self._reply(409, "another deploy is running\n")
        try:
            with tempfile.NamedTemporaryFile(suffix=".tgz") as f:
                f.write(body)
                f.flush()
                commit = self.headers.get("X-Commit", "unknown")[:64]
                proc = subprocess.run(
                    ["bash", str(DEPLOY_SH), f.name, commit],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600,
                )
            self._reply(200 if proc.returncode == 0 else 500, proc.stdout)
        except subprocess.TimeoutExpired:
            self._reply(504, "deploy timed out\n")
        finally:
            _lock.release()

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.headers.get("X-Real-IP") or self.client_address[0], fmt % args), flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
