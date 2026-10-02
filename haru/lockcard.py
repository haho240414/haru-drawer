"""잠금화면 카드 PNG 만들기 — 맥의 크롬(헤드리스)으로 app/lockcard.html 을 폰 해상도로 찍는다.

배경은 투명. 폰 앱이 사용자가 고른 배경 사진(또는 기본 그라데이션) 위에 겹쳐 잠금화면 배경으로 설정한다.
ES 모듈은 file:// 에서 안 돌아서 app/ 폴더를 잠깐 127.0.0.1 임시 서버로 띄워 찍는다.
"""
from __future__ import annotations

import base64
import functools
import json
import os
import shutil
import signal
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
]


def find_chrome() -> str | None:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    return shutil.which("google-chrome") or shutil.which("chromium")


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class StaticServer:
    """app/ 폴더를 잠깐 띄우는 서버 (with 문으로 사용)."""

    def __init__(self, root: Path):
        self.root = root

    def __enter__(self):
        handler = functools.partial(_Quiet, directory=str(self.root))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def card_from_digest(d: dict) -> dict:
    """app/js/common.js 의 cardFromDigest 와 같은 규칙 (맥 렌더 = 앱 미리보기)."""
    lock = d.get("lock") or {}
    lines = [x for x in (lock.get("lines") or []) if x]
    if not lines:
        by_id = {it["id"]: it for it in d.get("items", [])}
        lines = [(by_id[h["id"]].get("lock_line") or by_id[h["id"]].get("title"))
                 for h in d.get("highlights", []) if h.get("id") in by_id]
    stats = d.get("stats") or {}
    return {
        "day": d.get("day"), "label": d.get("label"),
        "count": stats.get("count") or len(d.get("items", [])),
        "title": lock.get("title") or d.get("headline") or "",
        "lines": [x for x in lines if x][:3],
        "todos": sum(1 for t in d.get("todos", []) if not t.get("done")),
        "readLater": len(d.get("read_later", [])),
        "cats": stats.get("categories") or [],
        "updated": (d.get("generated_at") or "")[11:16],
    }


def render(card: dict, style: str, out: Path, width: int = 1080, height: int = 2340, density: float = 3.0,
           timeout: int = 60) -> Path:
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("크롬을 찾지 못했어요 (잠금화면 카드는 크롬으로 그립니다)")
    css_w, css_h = round(width / density), round(height / density)
    data = base64.urlsafe_b64encode(json.dumps(card, ensure_ascii=False).encode()).decode().rstrip("=")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_profile = config.DATA / "chrome-profile"
    if out.exists():
        out.unlink()
    with StaticServer(config.WEB_DIR) as srv:
        url = f"http://127.0.0.1:{srv.port}/lockcard.html?style={style}&w={css_w}&h={css_h}#data={data}"
        cmd = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
               "--no-default-browser-check", f"--user-data-dir={tmp_profile}",
               # 새 프로필은 키체인을 열려다 멈출 수 있다 → 가짜 키체인·기본 비번 저장소
               "--use-mock-keychain", "--password-store=basic", "--disable-background-networking",
               "--disable-component-update", "--disable-sync", "--no-pings", "--mute-audio",
               "--default-background-color=00000000", f"--force-device-scale-factor={density}",
               f"--window-size={css_w},{css_h}", "--virtual-time-budget=2500",
               f"--screenshot={out}", url]
        # 함정: 이 맥의 크롬(헤드리스)은 스크린숏을 저장하고도 스스로 안 끝난다 → 파일이 다 써지면 끈다
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
        deadline, last_size, stable = time.time() + timeout, -1, 0
        try:
            while time.time() < deadline:
                if proc.poll() is not None and not out.exists():
                    break
                if out.exists():
                    size = out.stat().st_size
                    stable = stable + 1 if size == last_size and size > 0 else 0
                    last_size = size
                    if stable >= 3:
                        break
                time.sleep(0.15)
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
    if not out.exists():
        err = proc.stderr.read().decode("utf-8", "replace")[-300:] if proc.stderr else ""
        raise RuntimeError(f"카드 그리기 실패: {err}")
    # 크롬이 창 크기를 살짝 다르게 잡는 경우 정확히 폰 해상도로 맞춘다
    from PIL import Image
    with Image.open(out) as im:
        if im.size != (width, height):
            im = im.convert("RGBA").resize((width, height))
            im.save(out)
    return out


def render_for_digest(digest: dict, settings: dict, styles=("A", "B")) -> dict[str, Path]:
    dev = settings.get("device") or {}
    w, h, dens = int(dev.get("w", 1080)), int(dev.get("h", 2340)), float(dev.get("density", 3.0))
    card = card_from_digest(digest)
    out = {}
    for st in styles:
        p = config.CARDS / f"{digest['day']}_{st}.png"
        out[st] = render(card, st, p, w, h, dens)
    return out
