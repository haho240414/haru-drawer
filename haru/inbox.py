"""받은편지함(~/하루서랍) 과 '파일 넣기': 카톡 내보내기면 대화로, 아니면 사진·파일 한 장으로 넣는다."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from . import config, kakao, store
from .ingest import import_bundle, import_loose_file, IMAGE_EXT

LOOSE_EXT = IMAGE_EXT | {".pdf"}


def import_any(path: Path, settings: dict, allow_group: bool = False) -> dict:
    boundary = settings.get("day_boundary_hour", 4)
    path = Path(path)
    if path.is_dir():
        return {"file": path.name, **import_bundle(kakao.load_path(path), boundary, allow_group)}
    raw = path.read_bytes()
    if kakao.is_chat_export(path.name, raw):
        return {"file": path.name, **import_bundle(kakao.load_bytes(path.name, raw), boundary, allow_group)}
    if path.suffix.lower() in LOOSE_EXT:
        r, it = import_loose_file(path, boundary)
        return {"file": path.name, "kind": it["kind"], "result": r, "days": [it["day"]]}
    raise ValueError(f"{path.name}: 카톡 대화 파일·사진·PDF 만 넣을 수 있어요")


def import_upload(name: str, raw: bytes, settings: dict, allow_group: bool = False) -> dict:
    """대시보드에 끌어다 놓은 파일 (디스크 경로 없이 바이트로)."""
    tmp = config.DATA / "uploads" / name
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(raw)
    try:
        return import_any(tmp, settings, allow_group)
    finally:
        tmp.unlink(missing_ok=True)


def _fingerprint(p: Path) -> str:
    st = p.stat()
    return hashlib.sha1(f"{p.name}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:16]


def scan(settings: dict, log=print) -> list[str]:
    """받은편지함의 새 파일을 넣고 '처리됨' 폴더로 옮긴다. 영향을 받은 날짜 목록."""
    inbox = config.INBOX
    if not inbox.exists():
        return []
    done_dir = inbox / "처리됨"
    done_dir.mkdir(exist_ok=True)
    seen = set(store.kv_get("inbox_seen", []))
    days: set[str] = set()
    for p in sorted(inbox.iterdir()):
        if p.name.startswith(".") or p == done_dir or p.name == "처리됨":
            continue
        if p.is_file() and p.suffix.lower() in (".crdownload", ".part", ".download"):
            continue
        fp = _fingerprint(p)
        if fp in seen:
            continue
        try:
            res = import_any(p, settings)
            days |= set(res.get("days", []))
            log(f"받은편지함: {p.name} → {res.get('new', res.get('result'))}")
            target = done_dir / p.name
            if target.exists():
                target = done_dir / f"{p.stem}_{fp[:6]}{p.suffix}"
            shutil.move(str(p), str(target))
        except Exception as e:
            log(f"받은편지함: {p.name} 실패 — {e}")
            store.log_event("error", f"받은편지함 {p.name}: {str(e)[:160]}")
        seen.add(fp)
    store.kv_set("inbox_seen", sorted(seen)[-500:])
    return sorted(days)
