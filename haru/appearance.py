"""앱과 같은 테마를 저장 HTML에 포함하되 고정 스크립트만 허용한다."""
from __future__ import annotations

import base64
import hashlib

from . import config


def theme_script() -> tuple[str, str]:
    script = (config.WEB_DIR / "js/theme.js").read_text(encoding="utf-8")
    digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
    return f"sha256-{digest}", f"<script>{script}</script>"


def theme_css() -> str:
    return (config.WEB_DIR / "css/theme.css").read_text(encoding="utf-8")


def theme_control() -> str:
    return ('<label class="appearance" hidden><span>화면</span><select data-theme-select aria-label="화면 테마">'
            '<option value="system">시스템</option><option value="light">라이트</option>'
            '<option value="dark">다크</option></select></label>')
