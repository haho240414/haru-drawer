"""웹 대시보드와 함께 폰을 연결하고 완성된 보고서를 전달한다. 수집·AI 실행은 예약에 맡긴다."""
from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta

from . import config, daemon, store
from .pipeline import latest_day, publish_day
from .relay import Relay
from .timeutil import iso, now

log = logging.getLogger(__name__)


def next_report(settings: dict) -> str | None:
    yt = settings.get("youtube") or {}
    if not yt.get("enabled"):
        return daemon.next_schedule(settings)
    cur = now()
    target = cur.replace(hour=int(yt.get("report_hour", 22)), minute=0, second=0, microsecond=0)
    return iso(target if target > cur else target + timedelta(days=1))


def poll_once(settings: dict) -> None:
    rel = Relay.from_settings(settings)
    if rel is None:
        return
    # 실제 폰 연결 전에는 보고서 전송이 없다. 실패한 전달은 다음 바퀴에 재개한다.
    pending = set(store.kv_get("phone_bridge_pending", []))
    incoming = daemon.handle_phone(rel, settings, adopt_timezone=False)
    settings = config.load_settings()
    pending.update(d for d in incoming["resend"] if d)
    if incoming["refresh"]:
        pending.add(daemon.LATEST)
    store.kv_set("phone_bridge_pending", sorted(pending))
    for requested in sorted(pending):
        day = latest_day(settings) if requested == daemon.LATEST else requested
        if not day:
            pending.discard(requested)
        else:
            try:
                if publish_day(day, settings, log.info, force=True):
                    pending.discard(requested)
            except Exception as e:
                log.warning("폰 보고서 전달 대기: %s", type(e).__name__)
        store.kv_set("phone_bridge_pending", sorted(pending))
    if time.time() - float(store.kv_get("phone_bridge_hb", 0) or 0) > daemon.HEARTBEAT_SEC:
        rel.send_down({"t": "hb", "at": iso(now()), "next": next_report(settings), "day": latest_day(settings)})
        store.kv_set("phone_bridge_hb", time.time())
    store.kv_set("phone_bridge_tick", iso(now()))


def start() -> threading.Event:
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                poll_once(config.load_settings())
            except Exception as e:
                # 키·개인 내용은 로그에 남기지 않는다.
                log.warning("폰 연결 확인 대기: %s", type(e).__name__)
            stop.wait(30)

    threading.Thread(target=loop, name="haru-phone-bridge", daemon=True).start()
    return stop
