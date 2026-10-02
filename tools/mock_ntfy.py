"""시험용 가짜 ntfy 서버 (발행·폴링·첨부만). 단위 테스트와 CI 에서 실제 ntfy.sh 대신 쓴다.

  python tools/mock_ntfy.py --port 8899
지원: POST/PUT /<topic> (X-Filename/Filename, X-Message/Message), GET /<topic>/json?poll=1&since=…, GET /file/<id>.bin
"""
from __future__ import annotations

import argparse
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.msgs: dict[str, list[dict]] = {}
        self.files: dict[str, bytes] = {}
        self.expire_attachments = False   # 테스트에서 '3시간 지나 사라진 첨부' 흉내


STORE = Store()


def _since_filter(msgs: list[dict], since: str | None) -> list[dict]:
    if not since or since == "all":
        return msgs
    if since.endswith(("h", "m", "s")) and since[:-1].isdigit():
        mult = {"h": 3600, "m": 60, "s": 1}[since[-1]]
        cut = time.time() - int(since[:-1]) * mult
        return [m for m in msgs if m["time"] >= cut]
    if since.isdigit():
        return [m for m in msgs if m["time"] >= int(since)]
    ids = [m["id"] for m in msgs]
    if since in ids:
        return msgs[ids.index(since) + 1:]
    return msgs


class Handler(BaseHTTPRequestHandler):
    server_version = "mock-ntfy/1"
    base_url = ""

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _publish(self):
        topic = urlsplit(self.path).path.strip("/")
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        fname = self.headers.get("X-Filename") or self.headers.get("Filename")
        mid = secrets.token_urlsafe(9)[:12]
        msg = {"id": mid, "time": int(time.time()), "event": "message", "topic": topic}
        if fname:
            STORE.files[mid] = body
            msg["message"] = self.headers.get("X-Message") or self.headers.get("Message") or f"You received a file: {fname}"
            msg["attachment"] = {"name": fname, "type": "application/octet-stream", "size": len(body),
                                 "expires": int(time.time()) + 3 * 3600, "url": f"{self.base_url}/file/{mid}.bin"}
        else:
            msg["message"] = body.decode("utf-8", "replace")
        with STORE.lock:
            STORE.msgs.setdefault(topic, []).append(msg)
        self._json(msg)

    do_POST = _publish
    do_PUT = _publish

    def do_GET(self):
        sp = urlsplit(self.path)
        if sp.path.startswith("/file/"):
            mid = sp.path.split("/")[-1].split(".")[0]
            data = STORE.files.get(mid)
            if data is None or STORE.expire_attachments:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if sp.path.endswith("/json"):
            topic = sp.path.strip("/").rsplit("/", 1)[0]
            q = parse_qs(sp.query)
            with STORE.lock:
                msgs = list(STORE.msgs.get(topic, []))
            msgs = _since_filter(msgs, (q.get("since") or [None])[0])
            body = "".join(json.dumps(m) + "\n" for m in msgs).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json({"healthy": True})


def start(port: int = 0, host: str = "127.0.0.1") -> tuple[ThreadingHTTPServer, str]:
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{httpd.server_address[1]}"
    Handler.base_url = url
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, url


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--public-url", default=None, help="첨부 주소에 쓸 바깥 주소 (에뮬레이터: http://10.0.2.2:8899)")
    a = ap.parse_args()
    httpd, url = start(a.port, a.host)
    if a.public_url:
        Handler.base_url = a.public_url
    print(f"mock ntfy: {url} (첨부 주소 {Handler.base_url})", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
