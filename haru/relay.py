"""맥↔폰 중계 (ntfy.sh, 계정 없이 쓰는 공개 푸시 서버) + 페어링.

- 토픽 2개: up(폰→맥), down(맥→폰). 이름은 추측 불가능한 무작위 문자열.
- 모든 내용은 AES-GCM 으로 잠가서 보낸다 (crypto.py). 키는 페어링 QR 로만 폰에 간다.
- ntfy.sh 무료 한도(실측 문서 기준): 메시지 4,096바이트(넘으면 첨부로), 첨부 15MB·3시간 보관·IP당 100MB,
  메시지 12시간 보관, IP당 하루 250건. → 맥이 잠들어 3시간 넘게 못 받은 첨부는 'nack'으로 다시 보내 달라고 한다.
"""
from __future__ import annotations

import json
import secrets
import socket
import string
import time
from dataclasses import dataclass

import requests

from . import crypto

ALPHABET = string.ascii_lowercase + string.digits
MAX_TEXT = 3800          # 이보다 긴 글 메시지는 첨부로 보낸다


def new_topic() -> str:
    return "haru-" + "".join(secrets.choice(ALPHABET) for _ in range(22))


def new_pairing(server: str = "https://ntfy.sh") -> dict:
    return {"server": server, "up": new_topic(), "down": new_topic(), "key": crypto.new_key()}


def pairing_code(relay: dict, name: str | None = None) -> str:
    payload = {"v": 1, "s": relay["server"], "u": relay["up"], "d": relay["down"], "k": relay["key"],
               "n": name or socket.gethostname().split(".")[0]}
    return "HARU1." + crypto.b64u(json.dumps(payload, separators=(",", ":")).encode())


def parse_pairing_code(code: str) -> dict:
    code = code.strip()
    if not code.startswith("HARU1."):
        raise ValueError("하루서랍 연결 코드가 아니에요")
    p = json.loads(crypto.unb64u(code[6:]))
    return {"server": p["s"], "up": p["u"], "down": p["d"], "key": p["k"], "name": p.get("n", "")}


@dataclass
class Incoming:
    id: str
    time: int
    obj: dict
    attachment_url: str | None = None
    attachment_expires: int | None = None
    attachment_size: int | None = None


class Relay:
    def __init__(self, server: str, up: str, down: str, key: str, timeout: int = 30):
        self.server = server.rstrip("/")
        self.up, self.down, self.key = up, down, key
        self.timeout = timeout
        self.http = requests.Session()
        self.http.headers["User-Agent"] = "haru-drawer/0.1"

    @classmethod
    def from_settings(cls, settings: dict) -> "Relay | None":
        r = settings.get("relay") or {}
        if not (r.get("up") and r.get("down") and r.get("key")):
            return None
        return cls(r.get("server") or "https://ntfy.sh", r["up"], r["down"], r["key"])

    # ---------- 보내기 ----------
    def publish(self, topic: str, obj: dict, attachment: bytes | None = None, filename: str = "h.bin") -> str:
        url = f"{self.server}/{topic}"
        if attachment is None:
            body = crypto.seal_text(self.key, topic, obj)
            if len(body) <= MAX_TEXT:
                r = self.http.post(url, data=body.encode(), timeout=self.timeout)
                r.raise_for_status()
                return r.json().get("id", "")
            # 길면 내용 전체를 첨부로
            attachment = json.dumps(obj, ensure_ascii=False).encode()
            obj = {"t": obj.get("t"), "big": True}
        env = crypto.seal(self.key, topic, attachment)
        head = crypto.seal_text(self.key, topic, obj)
        r = self.http.put(url, data=env, timeout=max(self.timeout, 120),
                          headers={"X-Filename": filename, "X-Message": head})
        r.raise_for_status()
        return r.json().get("id", "")

    def send_down(self, obj: dict, attachment: bytes | None = None, filename: str = "h.bin") -> str:
        return self.publish(self.down, obj, attachment, filename)

    def send_up(self, obj: dict, attachment: bytes | None = None, filename: str = "h.bin") -> str:
        return self.publish(self.up, obj, attachment, filename)

    # ---------- 받기 ----------
    def poll(self, topic: str, since: str | int | None = None) -> list[Incoming]:
        params = {"poll": "1", "since": str(since) if since else "12h"}
        r = self.http.get(f"{self.server}/{topic}/json", params=params, timeout=self.timeout)
        r.raise_for_status()
        out: list[Incoming] = []
        for line in r.text.splitlines():
            if not line.strip():
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("event") != "message":
                continue
            try:
                obj = crypto.open_text(self.key, topic, m.get("message", ""))
            except (crypto.CryptoError, json.JSONDecodeError):
                continue   # 남의 메시지·깨진 메시지는 무시
            att = m.get("attachment") or {}
            out.append(Incoming(m["id"], int(m.get("time", 0)), obj, att.get("url"), att.get("expires"), att.get("size")))
        return out

    def fetch_attachment(self, inc: Incoming, topic: str) -> bytes | None:
        """첨부 내려받아 풀기. 만료(3시간)됐으면 None."""
        if not inc.attachment_url:
            return None
        if inc.attachment_expires and inc.attachment_expires < time.time():
            return None
        r = self.http.get(inc.attachment_url, timeout=max(self.timeout, 120))
        if r.status_code in (404, 410):
            return None
        r.raise_for_status()
        data = crypto.open_(self.key, topic, r.content)
        if inc.obj.get("big"):   # 긴 글 메시지가 첨부로 온 경우 → 원래 내용으로 바꾼다
            inc.obj = json.loads(data.decode())
            return None
        return data
