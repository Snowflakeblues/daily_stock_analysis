"""Small private ciphertext store; never receives the OAuth encryption key."""
import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import sqlite3
import time
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server

MAX_BYTES = 262144
STATE_PATH = "/internal/oauth-state"


class StateApplication:
    def __init__(self, database, key_hash):
        if len(key_hash) != 64:
            raise ValueError("Configure the storage credential hash.")
        self.database = str(database)
        self.key_hash = key_hash
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS records (collection TEXT NOT NULL, key TEXT NOT NULL, entry TEXT NOT NULL, expires_at REAL, PRIMARY KEY(collection,key))")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def dispatch(self, data):
        op = data.get("op")
        if op == "health":
            with self.connect() as db:
                db.execute("SELECT 1").fetchone()
            return {"ok": True}
        if op not in {"get", "put", "delete"}:
            raise ValueError()
        collection, key = data.get("collection"), data.get("key")
        if any(not isinstance(v, str) or not 1 <= len(v) <= 1024 for v in (collection, key)):
            raise ValueError()
        with self.connect() as db:
            db.execute("DELETE FROM records WHERE expires_at IS NOT NULL AND expires_at <= ?", (time.time(),))
            if op == "get":
                row = db.execute("SELECT entry FROM records WHERE collection=? AND key=?", (collection, key)).fetchone()
                return {"ok": True, "entry": row[0] if row else None}
            if op == "delete":
                result = db.execute("DELETE FROM records WHERE collection=? AND key=?", (collection, key))
                return {"ok": True, "deleted": result.rowcount > 0}
            entry, expires = data.get("entry"), data.get("expires_at")
            if not isinstance(entry, str) or len(entry.encode()) > 220000:
                raise ValueError()
            # Only Fernet-wrapped data is accepted. No plaintext token records.
            record = json.loads(entry)
            value = record.get("value", {})
            if not isinstance(value, dict) or set(value) != {"__encrypted_data__", "__encryption_version__"} or value["__encryption_version__"] != 1:
                raise ValueError()
            if not isinstance(value["__encrypted_data__"], str) or not base64.b64decode(value["__encrypted_data__"], validate=True).startswith(b"gAAAA"):
                raise ValueError()
            if expires is not None and (isinstance(expires, bool) or not isinstance(expires, (int, float)) or not math.isfinite(expires)):
                raise ValueError()
            db.execute("INSERT INTO records VALUES(?,?,?,?) ON CONFLICT(collection,key) DO UPDATE SET entry=excluded.entry,expires_at=excluded.expires_at", (collection, key, entry, expires))
            return {"ok": True}

    def __call__(self, environ, start_response):
        status, result = "200 OK", {"ok": True}
        try:
            if environ.get("PATH_INFO") != STATE_PATH:
                status, result = "404 Not Found", {"ok": False}
            elif environ.get("REQUEST_METHOD") != "POST":
                status, result = "405 Method Not Allowed", {"ok": False}
            else:
                auth = environ.get("HTTP_AUTHORIZATION", "")
                token = auth[7:] if auth.startswith("Bearer ") else ""
                if not token or len(token) > 512 or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), self.key_hash):
                    status, result = "401 Unauthorized", {"ok": False}
                elif environ.get("CONTENT_TYPE", "").split(";")[0] != "application/json":
                    status, result = "415 Unsupported Media Type", {"ok": False}
                else:
                    length = int(environ.get("CONTENT_LENGTH", "0"))
                    if not 0 < length <= MAX_BYTES:
                        status, result = "413 Content Too Large", {"ok": False}
                    else:
                        data = json.loads(environ["wsgi.input"].read(length))
                        if not isinstance(data, dict):
                            raise ValueError()
                        result = self.dispatch(data)
        except (ValueError, TypeError, KeyError):
            status, result = "400 Bad Request", {"ok": False}
        except Exception:
            status, result = "503 Service Unavailable", {"ok": False}
        raw = json.dumps(result, separators=(",", ":")).encode()
        start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(raw))), ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")])
        return [raw]


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


class ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    request_queue_size = 32
    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(10)
        return sock, address


if __name__ == "__main__":
    os.umask(0o077)
    app = StateApplication("/var/lib/frank-oauth-state/state.sqlite3", os.environ["STATE_KEY_SHA256"])
    with make_server("127.0.0.1", 9088, app, server_class=ThreadedServer, handler_class=QuietHandler) as server:
        server.serve_forever()
