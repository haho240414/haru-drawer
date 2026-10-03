"""한 번 돌리기: 새 항목 내용 가져오기 → AI 분석 → 하루 보고서 → 잠금화면 카드 → 폰으로 보내기."""
from __future__ import annotations

import base64
import fcntl
import json
import time
from contextlib import contextmanager
from pathlib import Path

from . import config, store
from .analyze import analyze_items, build_digest
from .enrich import enrich_link
from .timeutil import iso, now, today


class Busy(RuntimeError):
    pass


@contextmanager
def run_lock():
    config.ensure_dirs()
    f = open(config.DATA / "run.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        raise Busy("이미 정리 중이에요")
    try:
        f.write(str(time.time()))
        f.flush()
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def enrich_pending(log=print) -> list[str]:
    days = set()
    items = store.items_by_status(("new",))
    for n, it in enumerate(items, 1):
        meta = dict(it.get("meta") or {})
        try:
            if it["kind"] == "link" and it.get("url"):
                if it.get("url_key"):
                    prev = store.find_analyzed_by_url(it["url_key"], it["id"])
                    if prev and prev.get("meta", {}).get("title"):
                        meta = {**prev["meta"], **{k: v for k, v in meta.items() if v}}
                    else:
                        fetched = enrich_link(it["url"])
                        meta.update({k: v for k, v in fetched.items() if v} if it["source"] == "youtube" else fetched)
                else:
                    fetched = enrich_link(it["url"])
                    meta.update({k: v for k, v in fetched.items() if v} if it["source"] == "youtube" else fetched)
            elif it["kind"] == "file" and it.get("media", "").lower().endswith(".pdf"):
                meta["pdf_text"] = pdf_text(config.MEDIA / it["media"])
            elif it["kind"] == "image" and it.get("media"):
                p = config.MEDIA / it["media"]
                thumb = p.with_name(p.stem + ".thumb.jpg")
                if not thumb.exists():
                    from .ingest import make_thumb
                    make_thumb(p)
        except Exception as e:
            meta["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        store.update_item(it["id"], meta=meta, status="enriched")
        days.add(it["day"])
        if n % 5 == 0 or n == len(items):
            log(f"  내용 가져오기 {n}/{len(items)}")
    return sorted(days)


def pdf_text(path: Path, limit: int = 4000) -> str:
    try:
        from pypdf import PdfReader
        r = PdfReader(str(path))
        out = []
        for page in r.pages[:8]:
            out.append(page.extract_text() or "")
            if sum(len(x) for x in out) > limit:
                break
        return "\n".join(out)[:limit]
    except Exception as e:
        return f"(PDF 읽기 실패: {type(e).__name__})"


UPGRADE_DAYS = 3


def requeue_heuristic(settings: dict, log=print) -> set[str]:
    """AI 를 못 써서 규칙 기반으로 정리한 최근 항목을, AI 를 다시 쓸 수 있게 되면 다시 분석 대기로 돌린다."""
    from . import llm
    from .timeutil import shift_day, today
    if settings["llm"].get("backend") == "fake" or not llm.available(settings):
        return set()
    days: set[str] = set()
    t0 = today(settings.get("day_boundary_hour", 4))
    n = 0
    for k in range(UPGRADE_DAYS):
        day = shift_day(t0, -k)
        for it in store.items_for_day(day):
            a = it.get("analysis") or {}
            if it["status"] == "analyzed" and a.get("source") == "heuristic" and not (it.get("meta") or {}).get("placeholder") \
                    and it["kind"] not in ("video", "audio") and n < 30:
                store.update_item(it["id"], status="enriched")
                days.add(day)
                n += 1
        dg = store.get_digest(day)
        if dg and (dg.get("data") or {}).get("items") and dg["data"].get("llm", {}).get("backend") == "heuristic":
            days.add(day)
    if n:
        log(f"AI 를 다시 쓸 수 있어 규칙 기반으로 정리했던 {n}개를 다시 분석해요")
    return days


def latest_day(settings: dict) -> str | None:
    days = store.days_with_items(limit=1)
    return days[0]["day"] if days else None


def build_bundle(digest: dict, cards: dict[str, Path]) -> bytes:
    """폰으로 보낼 묶음: 보고서 + 잠금 카드 A/B + 사진 미리보기."""
    thumbs = {}
    for it in digest.get("items", []):
        if it.get("thumb"):
            p = config.MEDIA / it["thumb"]
            if p.exists() and p.stat().st_size < 120_000:
                thumbs[it["id"]] = base64.b64encode(p.read_bytes()).decode()
    payload = {
        "t": "bundle", "day": digest["day"], "ver": digest.get("version", 0),
        "digest": digest,
        "cards": {k: base64.b64encode(Path(v).read_bytes()).decode() for k, v in cards.items()},
        "thumbs": thumbs,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def publish_day(day: str, settings: dict, log=print, force: bool = False) -> bool:
    from .relay import Relay
    from .lockcard import render_for_digest
    rel = Relay.from_settings(settings)
    dg = store.get_digest(day)
    if not dg or not dg.get("data"):
        return False
    digest = dg["data"]
    digest["version"] = dg["version"]
    sig = f"{dg['version']}:{dg['item_sig']}:{json.dumps(settings.get('device'), sort_keys=True)}"
    cards = {st: config.CARDS / f"{day}_{st}.png" for st in ("A", "B")}
    if force or not all(p.exists() for p in cards.values()) or dg.get("published_sig") != sig:
        try:
            cards = render_for_digest(digest, settings)
        except Exception as e:
            log(f"잠금 카드 그리기 실패: {e}")
            store.log_event("error", f"잠금 카드 실패: {str(e)[:160]}")
            cards = {k: v for k, v in cards.items() if v.exists()}
    if rel is None:
        return False
    if dg.get("published_sig") == sig and not force:
        return False
    bundle = build_bundle(digest, cards)
    rel.send_down({"t": "digest", "day": day, "ver": dg["version"], "size": len(bundle)},
                  attachment=bundle, filename=f"{day}.bin")
    store.mark_published(day, sig)
    store.log_event("publish", f"{day} 보고서 v{dg['version']} 폰으로 보냄 ({len(bundle) // 1024}KB)")
    log(f"  폰으로 보냄: {day} v{dg['version']} ({len(bundle) // 1024}KB)")
    return True


def run(days: list[str] | None = None, publish: bool = True, force_digest: bool = False, log=print) -> dict:
    settings = config.load_settings()
    with run_lock():
        t0 = time.time()
        store.kv_set("run_state", {"running": True, "started": iso(now())})
        try:
            from .youtube import sync
            youtube = sync(settings, log)
            touched = set(enrich_pending(log))
            touched |= set(youtube["days"])
            upgrade = requeue_heuristic(settings, log)
            touched |= upgrade
            pending = store.items_by_status(("enriched",))
            if pending:
                log(f"AI 분석: {len(pending)}개")
                stats = analyze_items(pending, settings, log)
                touched |= {i["day"] for i in pending}
            else:
                stats = {}
            target = set(days or []) | touched
            if not target and force_digest:
                d = latest_day(settings)
                if d:
                    target.add(d)
            built = []
            for day in sorted(target):
                dg = build_digest(day, settings, force=force_digest or day in upgrade, log=log)
                if dg:
                    built.append(day)
            from .archive import export_day
            exported, export_errors = [], []
            for day in built:
                try:
                    folder = export_day(day, settings)
                    if folder:
                        exported.append(day)
                        log(f"  노트북에 저장: {folder}")
                except (OSError, ValueError) as e:
                    export_errors.append(day)
                    log(f"보고서 파일 저장 실패: {e}")
                    store.log_event("error", f"{day} 파일 저장 실패: {str(e)[:160]}")
            published = []
            if publish:
                # 폰에는 가장 최근 날(보통 오늘)만 — 예전 날 보고서는 폰이 요청하면 보낸다
                last = latest_day(settings)
                for day in sorted({d for d in built if d == last} | ({last} if last and force_digest else set())):
                    try:
                        if publish_day(day, settings, log):
                            published.append(day)
                    except Exception as e:
                        log(f"폰으로 보내기 실패: {e}")
                        store.log_event("error", f"보내기 실패: {str(e)[:160]}")
            result = {"ok": True, "days": sorted(target), "built": built, "published": published,
                      "exported": exported, "export_errors": export_errors,
                      "analysis": stats, "youtube": youtube, "sec": round(time.time() - t0, 1), "at": iso(now())}
            store.kv_set("last_run", result)
            store.log_event("run", f"정리 완료: 보고서 {len(built)}개, {result['sec']}초")
            return result
        finally:
            store.kv_set("run_state", {"running": False, "finished": iso(now())})


def current_day(settings: dict) -> str:
    return today(settings.get("day_boundary_hour", 4))
