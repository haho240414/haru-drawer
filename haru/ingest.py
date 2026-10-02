"""들어온 것(카톡 내보내기·폰 공유·받은편지함 파일)을 '항목'으로 바꿔 저장한다.

한 메시지에 링크가 여러 개면 링크마다 항목 하나. 같은 대화를 여러 번 내보내도
(분 단위 시각 + 내용) 으로 만든 ID 가 같아서 중복 저장되지 않는다.
텍스트만 내보낸 파일의 '사진'과 사진 포함 내보내기의 파일명은 같은 항목으로 합쳐져, 나중 것이 사진을 채운다.
"""
from __future__ import annotations

import hashlib
import io
import mimetypes
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import config, store
from .kakao import ExportBundle, Message
from .links import find_urls, normalize, site_kind
from .timeutil import day_of, iso

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v"}
AUDIO_EXT = {".m4a", ".mp3", ".aac", ".wav"}

RE_PHOTO = re.compile(r"^(사진|Photo|Photos)( ?\d+ ?장| \d+)?$", re.IGNORECASE)
RE_VIDEO = re.compile(r"^(동영상|Video)$", re.IGNORECASE)
RE_AUDIO = re.compile(r"^(음성메시지|보이스톡.*|Voice ?message)$", re.IGNORECASE)
RE_FILE = re.compile(r"^(파일|File)\s*:\s*(.+)$", re.IGNORECASE)
SKIP_TEXTS = {
    "이모티콘", "Emoticon", "Emoticons", "삭제된 메시지입니다.", "This message has been deleted.",
    "메시지가 삭제되었습니다.", "(이모티콘)", "샵검색", "투표", "일정",
}


def _h(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _kind_for_name(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    return "file"


def _norm_text(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()


def save_media(day: str, item_id: str, name: str, data: bytes) -> str:
    """원본을 MEDIA/<day>/ 에 저장하고, 사진이면 미리보기(긴 변 480)도 만든다. 상대 경로를 돌려준다."""
    ext = Path(name).suffix.lower() or (mimetypes.guess_extension("image/jpeg") or ".bin")
    rel = f"{day}/{item_id}{ext}"
    dst = config.MEDIA / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    if ext in IMAGE_EXT:
        make_thumb(dst)
    return rel


def make_thumb(path: Path, size: int = 480) -> Path | None:
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((size, size * 3))
            out = path.with_name(path.stem + ".thumb.jpg")
            im.save(out, "JPEG", quality=78)
            return out
    except Exception:
        return None


def items_from_messages(messages: list[Message], media: dict[str, bytes] | None, boundary: int,
                        source: str = "kakao", origin: str = "") -> list[dict]:
    media = media or {}
    occur: Counter = Counter()
    items: list[dict] = []
    for m in messages:
        if not m.sender:
            continue   # 맥 CSV 의 시스템 줄
        text = (m.text or "").strip()
        if not text or text in SKIP_TEXTS:
            continue
        ts_min = m.ts.replace(second=0, microsecond=0)
        tkey = ts_min.strftime("%Y-%m-%dT%H:%M")
        day = day_of(ts_min, boundary)
        base = {"day": day, "ts": iso(ts_min), "source": source, "origin": origin, "text": text}

        def make(content_key: str, **extra) -> dict:
            occur[(tkey, content_key)] += 1
            n = occur[(tkey, content_key)]
            it = dict(base, id="k:" + _h(tkey, content_key, str(n)), **extra)
            items.append(it)
            return it

        urls = find_urls(text)
        if urls:
            for u in urls:
                key = normalize(u)
                kind_site, label = site_kind(u)
                make("url:" + key, kind="link", url=u, url_key=key, meta={"site_kind": kind_site, "site": label})
            continue
        fname = text if "\n" not in text else ""
        if fname and fname in media:
            kind = _kind_for_name(fname)
            it = make("media:" + kind, kind=kind, meta={"filename": fname})
            it["_media_name"] = fname
            continue
        mf = RE_FILE.match(text)
        if mf:
            name = mf.group(2).strip()
            it = make("file:" + name, kind="file", meta={"filename": name})
            if name in media:
                it["_media_name"] = name
            continue
        if RE_PHOTO.match(text):
            make("media:image", kind="image", meta={"placeholder": True})
            continue
        if RE_VIDEO.match(text):
            make("media:video", kind="video", meta={"placeholder": True})
            continue
        if RE_AUDIO.match(text):
            make("media:audio", kind="audio", meta={"placeholder": True})
            continue
        make("text:" + _h(_norm_text(text)), kind="text", meta={})
    return items


def import_bundle(bundle: ExportBundle, boundary: int, allow_group: bool = False) -> dict:
    """카톡 내보내기 하나를 저장. 결과: 새 항목 수·중복·날짜 목록."""
    exp = bundle.export
    senders = exp.senders
    if len(senders) > 1 and not allow_group:
        raise ValueError(
            f"보낸 사람이 {len(senders)}명({', '.join(senders[:3])}…)인 대화예요. "
            "하루서랍은 '나와의 채팅' 내보내기만 받아요 (다른 사람 메시지가 분석에 들어가지 않게).")
    imp_id = "imp:" + _h(bundle.source_name, str(len(exp.messages)),
                         exp.messages[-1].ts.isoformat() if exp.messages else "")
    items = items_from_messages(exp.messages, bundle.media, boundary, "kakao", imp_id)
    stats = Counter()
    days: set[str] = set()
    for it in items:
        name = it.pop("_media_name", None)
        if name:
            it["media"] = save_media(it["day"], it["id"].replace(":", "_"), name, bundle.media[name])
        r = store.upsert_item(it)
        stats[r] += 1
        if r in ("new", "media"):
            days.add(it["day"])
    result = {"platform": exp.platform, "room": exp.room, "messages": len(exp.messages),
              "items": len(items), "new": stats["new"], "dup": stats["dup"], "media_filled": stats["media"],
              "days": sorted(days),
              "range": [items[0]["day"], items[-1]["day"]] if items else []}
    store.record_import(imp_id, bundle.source_name, exp.platform, result)
    store.log_event("import", f"{bundle.source_name}: 새 항목 {stats['new']}개 (중복 {stats['dup']})")
    return result


def import_share(share: dict, data: bytes | None, boundary: int) -> tuple[str, dict]:
    """폰 '공유하기'로 들어온 항목. share = {id, ts, kind, text, name, mime}."""
    ts = datetime.fromisoformat(share["ts"])
    day = day_of(ts, boundary)
    text = (share.get("text") or "").strip()
    sid = "s:" + str(share["id"])[:40]
    it = {"id": sid, "day": day, "ts": iso(ts), "source": "share", "origin": share.get("app") or "",
          "text": text, "meta": {}}
    urls = find_urls(text)
    if data is not None and share.get("kind") in ("image", "video", "file", "audio"):
        name = share.get("name") or ("shared" + (mimetypes.guess_extension(share.get("mime") or "") or ".bin"))
        it["kind"] = _kind_for_name(name) if share.get("kind") == "file" else share["kind"]
        it["meta"] = {"filename": name, "mime": share.get("mime")}
        it["media"] = save_media(day, sid.replace(":", "_"), name, data)
    elif urls:
        u = urls[0]
        kind_site, label = site_kind(u)
        it.update(kind="link", url=u, url_key=normalize(u), meta={"site_kind": kind_site, "site": label})
        if len(urls) > 1:
            it["meta"]["more_urls"] = urls[1:]
    else:
        it["kind"] = "text"
    r = store.upsert_item(it)
    return r, it


def import_loose_file(path: Path, boundary: int) -> tuple[str, dict]:
    """받은편지함에 그냥 떨어뜨린 사진·PDF (카톡 대화 파일이 아닌 것). 파일 수정 시각을 '보낸 시각'으로 본다."""
    st = path.stat()
    ts = datetime.fromtimestamp(st.st_mtime)
    share = {"id": "f" + _h(path.name, str(st.st_size), str(int(st.st_mtime))), "ts": iso(ts),
             "kind": _kind_for_name(path.name), "name": path.name, "app": "inbox"}
    r, it = import_share(share, path.read_bytes(), boundary)
    if r == "new":
        store.update_item(it["id"], source="inbox")
    return r, it


def bytes_to_jpeg(data: bytes, max_side: int = 1600) -> bytes:
    """분석용으로 줄인 JPEG (HEIC 등 낯선 형식도 열 수 있으면 변환)."""
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_side, max_side))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=85)
        return out.getvalue()
