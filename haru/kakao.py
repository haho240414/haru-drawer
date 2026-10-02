"""카카오톡 '대화 내용 내보내기' 파일 읽기.

플랫폼마다 형식이 다르다 (형식은 공개 뷰어 zeikar/kakaotalk-viewer 의 실사용 테스트 기준):
- 맥: CSV  — 첫 줄 'Date,User,Message', 날짜 '2021-12-29 20:36:00', 따옴표 안 줄바꿈·"" 이스케이프
- 윈도: TXT — '--------------- 2021년 12월 29일 수요일 ---------------' 구분선 + '[이름] [오후 10:10] 내용'
- 아이폰: TXT — 날짜 줄 '2021년 12월 29일 수요일' + '오후 8:36, 이름 : 내용'
          (또는 '2021. 12. 29. 오후 8:36, 이름 : 내용', 영어 'Dec 31, 2014 at 19:12, 이름 : 내용')
- 안드로이드: TXT — '2026년 4월 25일 오후 3:20, 이름 : 내용' (날짜 줄 '2026년 4월 25일 오후 3:20')
여러 줄 메시지는 다음 줄들이 이어 붙는다. 시스템 알림(초대·나감)은 버린다.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .timeutil import to24


@dataclass
class Message:
    ts: datetime          # 시간대 없는 한국 시각
    sender: str
    text: str


@dataclass
class Export:
    platform: str                     # mac | windows | ios | android
    room: str = ""
    messages: list[Message] = field(default_factory=list)

    @property
    def senders(self) -> list[str]:
        seen: dict[str, int] = {}
        for m in self.messages:
            if m.sender:
                seen[m.sender] = seen.get(m.sender, 0) + 1
        return sorted(seen, key=lambda s: -seen[s])


MONTHS_EN = {m: i + 1 for i, names in enumerate([
    ("Jan", "January"), ("Feb", "February"), ("Mar", "March"), ("Apr", "April"),
    ("May",), ("Jun", "June"), ("Jul", "July"), ("Aug", "August"),
    ("Sep", "Sept", "September"), ("Oct", "October"), ("Nov", "November"), ("Dec", "December"),
]) for m in names}
_MON = "|".join(sorted(MONTHS_EN, key=len, reverse=True))

# --- 날짜 줄 ---
RE_KO_DATE_WEEKDAY = re.compile(r"^(\d{4})년 (\d{1,2})월 (\d{1,2})일 [월화수목금토일]요일$")
RE_KO_DATE_TIME = re.compile(r"^(\d{4})년 (\d{1,2})월 (\d{1,2})일 (오전|오후) (\d{1,2}):(\d{2})$")
RE_EN_DATE_LINE = re.compile(rf"^\w+, ({_MON}) (\d{{1,2}}), (\d{{4}})$")
RE_WIN_SEP_KO = re.compile(r"^-{10,} (\d{4})년 (\d{1,2})월 (\d{1,2})일 .*?-{10,}$")
RE_WIN_SEP_EN = re.compile(rf"^-{{10,}} \w+, ({_MON}) (\d{{1,2}}), (\d{{4}}) -{{10,}}$")

# --- 메시지 줄 ---
RE_ANDROID = re.compile(r"^(\d{4})년 (\d{1,2})월 (\d{1,2})일 (오전|오후) (\d{1,2}):(\d{2}), (.*?) : (.*)$")
RE_ANDROID_EN = re.compile(
    rf"^({_MON}) (\d{{1,2}}), (\d{{4}}),? (?:at )?(\d{{1,2}}):(\d{{2}})(?: ?([AP]M))?, (.*?) : (.*)$")
RE_IOS_TIME = re.compile(r"^(오전|오후) (\d{1,2}):(\d{2}), (.*?) : (.*)$")
RE_IOS_DOTTED = re.compile(r"^(\d{4})\. ?(\d{1,2})\. ?(\d{1,2})\.? (오전|오후) (\d{1,2}):(\d{2}), (.*?) : (.*)$")
RE_IOS_EN = re.compile(rf"^({_MON}) (\d{{1,2}}), (\d{{4}}) at (\d{{1,2}}):(\d{{2}}), (.*?) : (.*)$")
RE_WIN_MSG = re.compile(r"^\[(.*?)\] \[(?:(오전|오후|AM|PM) )?(\d{1,2}):(\d{2})(?: ?(AM|PM))?\] (.*)$")

# 시스템 알림 (내용 아님)
RE_NOTI = [
    re.compile(r"^(\d{4})년 (\d{1,2})월 (\d{1,2})일 (오전|오후) (\d{1,2}):(\d{2}), [^:]*$"),
    re.compile(r"^(오전|오후) (\d{1,2}):(\d{2}), [^:]*$"),
    re.compile(r".+님(이|을) (나갔습니다|초대하였습니다|들어왔습니다)\.?$"),
    re.compile(r".+ (joined|left) this chatroom\.$"),
]


def decode_bytes(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def detect_platform(text: str) -> str:
    lines = text.lstrip("﻿").splitlines()
    if lines and "Date,User,Message" in lines[0]:
        return "mac"
    body = [ln for ln in lines[2:60] if ln.strip()]
    for ln in body:
        if RE_WIN_SEP_KO.match(ln) or RE_WIN_SEP_EN.match(ln):
            return "windows"
        if RE_WIN_MSG.match(ln):
            return "windows"
    for ln in body:
        if RE_KO_DATE_WEEKDAY.match(ln) or RE_EN_DATE_LINE.match(ln):
            continue
        if RE_IOS_TIME.match(ln) or RE_IOS_DOTTED.match(ln) or RE_IOS_EN.match(ln):
            return "ios"
        if RE_ANDROID.match(ln) or RE_ANDROID_EN.match(ln) or RE_KO_DATE_TIME.match(ln):
            return "android"
    return "android"


def _room_from_header(first: str) -> str:
    first = first.lstrip("﻿").strip()
    m = re.match(r"^(.*?) ?(님과)? 카카오톡 대화$", first)
    if m:
        return m.group(1).strip()
    return first


def parse_text(text: str) -> Export:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    platform = detect_platform(text)
    if platform == "mac":
        return _parse_mac_csv(text)
    lines = text.lstrip("﻿").split("\n")
    exp = Export(platform=platform, room=_room_from_header(lines[0]) if lines else "")
    cur_date: tuple[int, int, int] | None = None
    started = False
    last: Message | None = None

    def add(y, mo, d, h, mi, sender, body):
        nonlocal last
        msg = Message(datetime(int(y), int(mo), int(d), int(h), int(mi)), sender.strip(), body)
        exp.messages.append(msg)
        last = msg

    for ln in lines[1:]:
        if not started:
            # 머리말(저장한 날짜 등)은 첫 날짜·메시지 줄이 나올 때까지 건너뛴다
            if ln.startswith("저장한 날짜") or ln.startswith("Date Saved") or not ln.strip():
                continue
        stripped = ln.rstrip()
        m = None
        if platform == "windows":
            m = RE_WIN_SEP_KO.match(stripped)
            if m:
                cur_date, started, last = (int(m[1]), int(m[2]), int(m[3])), True, None
                continue
            m = RE_WIN_SEP_EN.match(stripped)
            if m:
                cur_date, started, last = (int(m[3]), MONTHS_EN[m[1]], int(m[2])), True, None
                continue
            m = RE_WIN_MSG.match(stripped)
            if m and cur_date:
                ampm = m[2] or m[5]
                add(*cur_date, to24(int(m[3]), ampm), m[4], m[1], m[6])
                started = True
                continue
        elif platform == "ios":
            m = RE_KO_DATE_WEEKDAY.match(stripped)
            if m:
                cur_date, started, last = (int(m[1]), int(m[2]), int(m[3])), True, None
                continue
            m = RE_EN_DATE_LINE.match(stripped)
            if m:
                cur_date, started, last = (int(m[3]), MONTHS_EN[m[1]], int(m[2])), True, None
                continue
            m = RE_IOS_DOTTED.match(stripped)
            if m:
                add(m[1], m[2], m[3], to24(int(m[5]), m[4]), m[6], m[7], m[8])
                started = True
                continue
            m = RE_IOS_EN.match(stripped)
            if m:
                add(m[3], MONTHS_EN[m[1]], m[2], m[4], m[5], m[6], m[7])
                started = True
                continue
            m = RE_IOS_TIME.match(stripped)
            if m and cur_date:
                add(*cur_date, to24(int(m[2]), m[1]), m[3], m[4], m[5])
                started = True
                continue
        else:  # android
            m = RE_KO_DATE_TIME.match(stripped) or RE_KO_DATE_WEEKDAY.match(stripped)
            if m and "," not in stripped:
                cur_date, started, last = (int(m[1]), int(m[2]), int(m[3])), True, None
                continue
            m = RE_ANDROID.match(stripped)
            if m:
                add(m[1], m[2], m[3], to24(int(m[5]), m[4]), m[6], m[7], m[8])
                started = True
                continue
            m = RE_ANDROID_EN.match(stripped)
            if m:
                add(m[3], MONTHS_EN[m[1]], m[2], to24(int(m[4]), m[6]), m[5], m[7], m[8])
                started = True
                continue
        if any(r.match(stripped) for r in RE_NOTI):
            last = None   # 알림 뒤 줄은 앞 메시지에 이어 붙이지 않는다
            continue
        if last is not None and started:
            last.text += "\n" + ln
    for msg in exp.messages:
        msg.text = msg.text.rstrip()
    return exp


def _parse_mac_csv(text: str) -> Export:
    exp = Export(platform="mac")
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = next(reader, None)
    for row in reader:
        if len(row) < 3:
            continue
        raw_date, user, body = row[0].strip(), row[1], ",".join(row[2:]) if len(row) > 3 else row[2]
        if not raw_date:
            continue  # 날짜 없는 줄 = 시스템 알림
        try:
            ts = datetime.fromisoformat(raw_date.replace("/", "-"))
        except ValueError:
            continue
        if any(r.match(body) for r in RE_NOTI[2:]) or re.match(r"^.* invited .*\.$", body):
            continue
        exp.messages.append(Message(ts.replace(second=0, microsecond=0), user.strip(), body.rstrip()))
    users = exp.senders
    exp.room = ", ".join(users[:3])
    _ = header
    return exp


# ---------- 파일·압축·폴더 ----------
MEDIA_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp",
             ".mp4", ".mov", ".m4v", ".pdf", ".m4a", ".mp3", ".zip", ".docx", ".xlsx", ".pptx", ".hwp", ".txt"}


@dataclass
class ExportBundle:
    export: Export
    media: dict[str, bytes] = field(default_factory=dict)   # 파일 이름 → 내용
    source_name: str = ""


def _looks_like_chat(name: str, text: str) -> bool:
    head = text[:400]
    return ("카카오톡 대화" in head or "Date,User,Message" in head or "저장한 날짜" in head
            or "Date Saved" in head or name.lower().startswith(("kakaotalk", "talk_")))


def load_path(path: Path) -> ExportBundle:
    """.txt/.csv 파일, .zip(아이폰 '도큐멘트로 저장'), 폴더(안드로이드 '내부 저장소에 저장') 모두 받는다."""
    path = Path(path)
    if path.is_dir():
        chat_file, media = None, {}
        for p in sorted(path.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix.lower() in (".txt", ".csv") and chat_file is None:
                t = decode_bytes(p.read_bytes())
                if _looks_like_chat(p.name, t):
                    chat_file = (p.name, t)
                    continue
            if p.suffix.lower() in MEDIA_EXT:
                media[p.name] = p.read_bytes()
        if not chat_file:
            raise ValueError("폴더 안에서 카톡 대화 파일(.txt/.csv)을 못 찾았어요")
        return ExportBundle(parse_text(chat_file[1]), media, path.name)
    raw = path.read_bytes()
    return load_bytes(path.name, raw)


def load_bytes(name: str, raw: bytes) -> ExportBundle:
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            chat, media = None, {}
            for info in z.infolist():
                if info.is_dir():
                    continue
                base = Path(info.filename).name
                if base.startswith("._") or "__MACOSX" in info.filename:
                    continue
                data = z.read(info)
                suffix = Path(base).suffix.lower()
                if suffix in (".txt", ".csv") and chat is None:
                    t = decode_bytes(data)
                    if _looks_like_chat(base, t):
                        chat = t
                        continue
                if suffix in MEDIA_EXT:
                    media[base] = data
            if chat is None:
                raise ValueError("압축 파일 안에서 카톡 대화 파일(.txt/.csv)을 못 찾았어요")
            return ExportBundle(parse_text(chat), media, name)
    text = decode_bytes(raw)
    return ExportBundle(parse_text(text), {}, name)


def is_chat_export(name: str, raw: bytes) -> bool:
    if raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                return any(Path(i.filename).suffix.lower() in (".txt", ".csv") for i in z.infolist())
        except zipfile.BadZipFile:
            return False
    if Path(name).suffix.lower() not in (".txt", ".csv", ""):
        return False
    return _looks_like_chat(name, decode_bytes(raw[:2000]))
