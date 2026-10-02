"""상시 실행 (launchd KeepAlive): 폰이 보낸 것 받기 · 받은편지함 감시 · 정해진 시각 정리 · 폰에 살아 있음 알리기.

맥이 잠들었다 깨어나도 그냥 다음 바퀴부터 이어서 돈다 (밀린 정리는 깨어난 뒤 한 번).
"""
from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from . import config, inbox, store
from .ingest import import_bundle, import_share
from .kakao import load_bytes
from .pipeline import Busy, latest_day, publish_day, run
from .relay import Relay
from .timeutil import iso, now, parse_iso

LOOP_SEC = 30
HEARTBEAT_SEC = 3600
SHARE_QUIET_SEC = 180      # 폰 공유가 이만큼 잠잠해지면 정리
log = logging.getLogger("haru")
_stop = False


def setup_logging() -> None:
    config.ensure_dirs()
    log.setLevel(logging.INFO)
    if not log.handlers:
        # 로그 시각도 하루서랍 시간대로 (이 맥의 시스템 시간대는 LA 라서)
        def conv(*_):
            return now().timetuple()
        fmt_file = logging.Formatter("%(asctime)s %(message)s", "%m-%d %H:%M:%S")
        fmt_out = logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S")
        fmt_file.converter = fmt_out.converter = conv
        fh = RotatingFileHandler(config.LOGS / "daemon.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt_file)
        log.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt_out)
        log.addHandler(sh)


def schedule_due(settings: dict) -> datetime | None:
    """가장 최근에 지난 정리 시각이 아직 안 돌았으면 그 시각."""
    cur = now()
    last = store.kv_get("last_sched")
    last_dt = parse_iso(last) if last else cur - timedelta(days=1)
    latest = None
    for hm in settings.get("schedule", []):
        try:
            h, m = (int(x) for x in hm.split(":"))
        except ValueError:
            continue
        for back in (0, 1):
            t = (cur - timedelta(days=back)).replace(hour=h, minute=m, second=0, microsecond=0)
            if t <= cur and (latest is None or t > latest):
                latest = t
    if latest and latest > last_dt:
        return latest
    return None


def next_schedule(settings: dict) -> str | None:
    cur = now()
    cands = []
    for hm in settings.get("schedule", []):
        try:
            h, m = (int(x) for x in hm.split(":"))
        except ValueError:
            continue
        t = cur.replace(hour=h, minute=m, second=0, microsecond=0)
        cands.append(t if t > cur else t + timedelta(days=1))
    return iso(min(cands)) if cands else None


def handle_phone(rel: Relay, settings: dict) -> dict:
    """폰 → 맥 메시지 처리. 결과: {'items': n, 'refresh': bool, 'resend': [days]}"""
    st = store.kv_get("up_state", {"since": 0, "seen": []})
    seen = set(st.get("seen", []))
    since = max(int(st.get("since", 0)) - 180, int(time.time()) - 12 * 3600)
    incs = rel.poll(rel.up, since=since)
    acks, nacks, out = [], [], {"items": 0, "refresh": False, "resend": []}
    boundary = settings.get("day_boundary_hour", 4)
    for inc in sorted(incs, key=lambda i: i.time):
        if inc.id in seen:
            continue
        obj = inc.obj
        t = obj.get("t")
        try:
            if t == "hello":
                dev = obj.get("dev") or {}
                patch: dict = {}
                if dev.get("w") and dev.get("h"):
                    patch["device"] = {"w": int(dev["w"]), "h": int(dev["h"]),
                                       "density": float(dev.get("density") or 3.0), "model": dev.get("model", "")}
                if obj.get("tz") and obj["tz"] != settings.get("timezone"):
                    patch["timezone"] = obj["tz"]
                if patch:
                    settings = config.update_settings(patch)
                store.kv_set("phone", {"seen": iso(now()), "dev": dev, "app": obj.get("app"), "tz": obj.get("tz")})
                store.log_event("phone", f"폰 연결: {dev.get('model', '')} {dev.get('w')}×{dev.get('h')}")
                log.info("폰 인사: %s", dev)
                out["resend"].append(latest_day(settings))
                send_heartbeat(rel, settings)
            elif t == "item":
                data = None
                if inc.attachment_url:
                    data = rel.fetch_attachment(inc, rel.up)
                    obj = inc.obj
                    if data is None and not obj.get("big") and obj.get("kind") in ("image", "file", "video", "audio", "export"):
                        nacks.append(obj.get("id"))     # 첨부가 3시간 넘어 사라짐 → 다시 보내 달라
                        seen.add(inc.id)
                        continue
                if obj.get("kind") == "export" and data is not None:
                    res = import_bundle(load_bytes(obj.get("name") or "export.txt", data), boundary)
                    log.info("폰에서 카톡 내보내기: 새 %s개", res["new"])
                else:
                    r, it = import_share(obj, data, boundary)
                    log.info("폰 공유: %s %s (%s)", it["kind"], (it.get("url") or it.get("text") or "")[:60], r)
                acks.append(obj.get("id"))
                out["items"] += 1
                store.kv_set("last_share_at", time.time())
                store.kv_set("phone_items_total", int(store.kv_get("phone_items_total", 0) or 0) + 1)
            elif t == "refresh":
                out["refresh"] = True
            elif t == "resend":
                out["resend"].append(obj.get("day") or latest_day(settings))
            elif t == "todo":
                store.set_todo_done(obj.get("key", ""), bool(obj.get("done")))
            store.kv_set("phone_last", iso(now()))
        except Exception as e:
            log.exception("폰 메시지 처리 실패: %s", e)
            store.log_event("error", f"폰 메시지 처리 실패: {str(e)[:160]}")
        seen.add(inc.id)
    if acks or nacks:
        rel.send_down({"t": "ack", "ids": [a for a in acks if a], "nack": [n for n in nacks if n]})
    st = {"since": max([i.time for i in incs], default=st.get("since", 0)), "seen": list(seen)[-400:]}
    store.kv_set("up_state", st)
    return out


def send_heartbeat(rel: Relay, settings: dict) -> None:
    last_run = store.kv_get("last_run") or {}
    rel.send_down({"t": "hb", "at": iso(now()), "next": next_schedule(settings), "last_run": last_run.get("at"),
                   "day": latest_day(settings)})
    store.kv_set("last_hb", time.time())


def loop_once(settings: dict) -> None:
    rel = Relay.from_settings(settings)
    want_run, resend = False, []
    if rel:
        try:
            r = handle_phone(rel, settings)
            want_run |= r["refresh"]
            resend += [d for d in r["resend"] if d]
            settings = config.load_settings()
            if time.time() - float(store.kv_get("last_hb", 0) or 0) > HEARTBEAT_SEC:
                send_heartbeat(rel, settings)
        except Exception as e:
            log.warning("중계 서버 연결 실패: %s", e)
    try:
        if inbox.scan(settings, log.info):
            want_run = True
    except Exception as e:
        log.warning("받은편지함 실패: %s", e)
    due = schedule_due(settings)
    if due:
        want_run = True
    req = store.kv_get("run_request")
    if req:
        want_run = True
    # 폰 공유로 새 항목이 들어왔고 잠잠해졌으면 정리 (너무 자주는 안 돌게 최소 간격)
    pending = store.items_by_status(("new", "enriched"))
    last_share = float(store.kv_get("last_share_at", 0) or 0)
    last_run_ts = float(store.kv_get("last_run_ts", 0) or 0)
    min_gap = int(settings.get("min_run_gap_min", 20)) * 60
    if pending and time.time() - last_share > SHARE_QUIET_SEC and time.time() - last_run_ts > min_gap:
        want_run = True
    if want_run:
        try:
            res = run(publish=True, force_digest=bool(req and req.get("force")), log=log.info)
            log.info("정리 완료: %s", {k: res[k] for k in ("built", "published", "sec")})
            store.kv_set("last_run_ts", time.time())
            if due:
                store.kv_set("last_sched", iso(due))
            store.kv_set("run_request", None)
        except Busy:
            log.info("다른 정리가 돌고 있어 다음 바퀴로")
        except Exception as e:
            log.exception("정리 실패: %s", e)
            store.log_event("error", f"정리 실패: {str(e)[:200]}")
            if due:
                store.kv_set("last_sched", iso(due))   # 같은 시각으로 무한 재시도하지 않게
            store.kv_set("run_request", None)
    for day in set(resend):
        try:
            publish_day(day, settings, log.info, force=True)
        except Exception as e:
            log.warning("다시 보내기 실패: %s", e)


def main() -> None:
    setup_logging()
    settings = config.load_settings()
    log.info("하루서랍 데몬 시작 (시간대 %s, 받은편지함 %s)", settings.get("timezone"), config.INBOX)

    def _term(*_):
        global _stop
        _stop = True
    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)
    store.kv_set("daemon", {"pid": __import__("os").getpid(), "started": iso(now())})
    while not _stop:
        t0 = time.time()
        try:
            loop_once(config.load_settings())
        except Exception as e:
            log.exception("바퀴 실패: %s", e)
        store.kv_set("daemon_tick", iso(now()))
        while not _stop and time.time() - t0 < LOOP_SEC:
            time.sleep(1)
    log.info("데몬 종료")
