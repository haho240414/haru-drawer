"""시간: 하루서랍 시간대(기본 Asia/Seoul — 폰이 알려 주면 폰 시간대)로 센다. '하루'는 새벽 경계(기본 4시)로 자른다.

이 맥의 시스템 시간대는 미국(LA)으로 되어 있어(2026-10 확인) 맥 시계를 그대로 쓰면 날짜가 하루씩 밀린다.
카톡 내보내기 시각은 시간대가 없는 '폰 현지 시각'이라 그대로 쓰고, '지금'만 설정 시간대로 계산한다."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")   # 현재 설정 시간대 (set_tz 로 바뀜, 이름은 그대로 둠)


def set_tz(name: str | None) -> None:
    global KST
    try:
        KST = ZoneInfo(name or "Asia/Seoul")
    except Exception:
        KST = ZoneInfo("Asia/Seoul")


WEEKDAYS = "월화수목금토일"


def now() -> datetime:
    return datetime.now(KST)


def as_kst(dt: datetime) -> datetime:
    """시간대 없는 시각은 한국 시간으로 본다 (카톡 내보내기 파일은 시간대가 없다)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def day_of(dt: datetime, boundary_hour: int = 4) -> str:
    return (as_kst(dt) - timedelta(hours=boundary_hour)).date().isoformat()


def today(boundary_hour: int = 4) -> str:
    return day_of(now(), boundary_hour)


def iso(dt: datetime) -> str:
    return as_kst(dt).isoformat(timespec="seconds")


def parse_iso(s: str) -> datetime:
    return as_kst(datetime.fromisoformat(s))


def shift_day(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def day_label(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d.month}월 {d.day}일 ({WEEKDAYS[d.weekday()]})"


def to24(hour: int, ampm: str | None) -> int:
    """'오후 3' → 15, '오전 12' → 0. ampm 이 없으면 그대로."""
    if not ampm:
        return hour
    ampm = ampm.strip().upper()
    if ampm in ("오전", "AM"):
        return 0 if hour == 12 else hour
    return hour if hour == 12 else hour + 12
