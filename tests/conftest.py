import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "fixtures"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """실제 ~/.haru-drawer 를 건드리지 않게 임시 폴더로 바꾼다."""
    from haru import config, store
    h = tmp_path / "home"
    monkeypatch.setattr(config, "HOME", h)
    monkeypatch.setattr(config, "DATA", h / "data")
    monkeypatch.setattr(config, "DB_PATH", h / "data" / "haru.db")
    monkeypatch.setattr(config, "MEDIA", h / "data" / "media")
    monkeypatch.setattr(config, "CARDS", h / "data" / "cards")
    monkeypatch.setattr(config, "LOGS", h / "logs")
    monkeypatch.setattr(config, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(config, "SETTINGS_PATH", h / "data" / "settings.json")
    store.reset_connection()
    config.ensure_dirs()
    yield h
    store.reset_connection()
