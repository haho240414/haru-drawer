"""경로와 설정.

코드는 ~/Documents/haru-drawer 에 있지만, launchd 로 도는 실행본과 데이터는 ~/.haru-drawer 에 둔다
(~/Documents·~/Downloads 는 macOS 개인정보 보호(TCC)로 백그라운드 프로세스가 못 읽는다).
카톡 내보내기 파일을 떨어뜨리는 받은편지함은 홈 바로 아래 ~/하루서랍 (보호 폴더가 아니라 백그라운드에서도 읽힘).
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

HOME = Path(os.environ.get("HARU_HOME", str(Path.home() / ".haru-drawer")))
DATA = HOME / "data"
DB_PATH = DATA / "haru.db"
MEDIA = DATA / "media"
CARDS = DATA / "cards"
LOGS = HOME / "logs"
INBOX = Path(os.environ.get("HARU_INBOX", str(Path.home() / "하루서랍")))
SETTINGS_PATH = DATA / "settings.json"

# 프로젝트 안의 웹 앱(폰 앱과 맥 대시보드가 같이 쓰는 화면)
PKG_DIR = Path(__file__).resolve().parent
ROOT = PKG_DIR.parent
WEB_DIR = ROOT / "app"

DEFAULTS: dict = {
    # 시간대 (폰이 연결되면 폰 시간대로 자동 갱신)
    "timezone": "Asia/Seoul",
    # 새벽 4시 전까지는 '어제'로 친다 (밤늦게 보낸 것도 그날 정리에 들어가게)
    "day_boundary_hour": 4,
    # 정리 돌리는 시각 (맥이 잠들어 있었으면 깨어난 뒤 한 번)
    "schedule": ["08:00", "12:30", "18:30", "22:00"],
    "llm": {
        "backend": "codex",       # codex | ollama | fake
        "effort": "low",          # codex 추론 강도 (low 로도 캡처 판독 정확, 12초 안팎)
        "digest_effort": "medium",
        "model": None,
        "batch": 5,               # 한 번에 분석할 항목 수
        "timeout": 300,
        # Codex 사용 한도가 차면 이 맥의 로컬 모델로 대신 (qwen3.6:27b: 캡처 읽기 가능, 항목당 1분 안팎)
        "fallback": "ollama",
        "ollama_model": "qwen3.6:27b",
        "ollama_batch": 3,
        "ollama_timeout": 1200,
    },
    "relay": {
        "server": "https://ntfy.sh",
        "up": None,      # 폰 → 맥
        "down": None,    # 맥 → 폰
        "key": None,     # AES-256 키 (base64url) — 페어링 QR 로만 폰에 전달
    },
    "categories": [
        "부동산", "재테크·투자", "AI·테크", "업무", "콘텐츠·SNS",
        "쇼핑", "건강·운동", "맛집·여행", "생활·정보", "기타",
    ],
    # 분석할 때 참고하는 사용자 소개 (설정에서 고칠 수 있음)
    "profile": "부동산·재테크, AI 자동화, 콘텐츠 제작에 관심이 많은 직장인. 링크·캡처를 카톡 '나에게 보내기'로 모아 둔다.",
    # 폰이 페어링 때 알려 주는 화면 크기 (모르면 갤럭시 S 기본값)
    "device": {"w": 1080, "h": 2340, "density": 3.0, "model": ""},
    "port": 8891,
    # 같은 보고서를 노트북의 읽을 수 있는 파일·분류 폴더로도 보관.
    "archive": {"enabled": True, "directory": None},  # 기본 ~/하루서랍/정리
}


def _deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def ensure_dirs() -> None:
    for p in (DATA, MEDIA, CARDS, LOGS):
        p.mkdir(parents=True, exist_ok=True)
    try:
        INBOX.mkdir(parents=True, exist_ok=True)
        (INBOX / "처리됨").mkdir(exist_ok=True)
    except OSError:
        pass


def load_settings() -> dict:
    data = {}
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    s = _deep_merge(DEFAULTS, data)
    from .timeutil import set_tz
    set_tz(s.get("timezone"))
    return s


def save_settings(settings: dict) -> None:
    ensure_dirs()
    # 기본값과 다른 것만 저장하면 기본값이 바뀔 때 따라가지만, 단순하게 전체 저장
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(SETTINGS_PATH)


def update_settings(patch: dict) -> dict:
    s = _deep_merge(load_settings(), patch)
    save_settings(s)
    return s
