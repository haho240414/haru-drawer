"""노트북 파일과 폰 보고서가 같은 분석 결과를 사용하는지 검증."""
import csv
import io
import json
import re
from pathlib import Path

import pytest

from haru import archive, config, inbox, pipeline, store
from haru.ingest import import_share
from haru.server import app

DAY = "2026-10-03"


def memo(home):
    config.update_settings({"llm": {"backend": "fake"}})
    import_share({"id": "archive-memo", "ts": f"{DAY}T10:00:00+09:00", "kind": "text",
                  "text": "관리사무소에 전화하기\n토요일 오전 10시 임장 준비"}, None, 4)
    return pipeline.run(publish=False, log=lambda *_: None)


def test_pipeline_writes_readable_report_and_updates_todo(home):
    result = memo(home)
    assert result["exported"] == [DAY] and result["export_errors"] == []
    folder = archive.day_dir(DAY)
    doc = json.loads((folder / "보고서.json").read_text())
    assert doc["version"] == store.get_digest(DAY)["version"]
    assert doc["items"] == store.get_digest(DAY)["data"]["items"]
    assert "관리사무소" in (folder / "보고서.md").read_text()
    assert list((folder / "분류").rglob("*.md"))
    key = doc["todos"][0]["key"]
    client = app.test_client()
    assert client.post("/api/todo", json={"key": key, "done": True}).status_code == 200
    assert "- [x]" in (folder / "할일.md").read_text()
    assert json.loads((folder / "보고서.json").read_text())["todos"][0]["done"] is True
    assert client.get(f"/reports/{DAY}/보고서.html").status_code == 200
    assert client.get(f"/reports/{DAY}/{archive.MANIFEST}").status_code == 404
    (folder / "개인메모.md").write_text("내가 추가한 메모")
    assert client.get(f"/reports/{DAY}/개인메모.md").status_code == 404


def test_removal_clears_exported_items_and_preserves_personal_notes(home):
    memo(home)
    folder = archive.day_dir(DAY)
    note = folder / "개인메모.md"
    note.write_text("사용자의 메모")
    item_file = next((folder / "분류").rglob("*.md"))
    client = app.test_client()
    assert client.post("/api/item/s:archive-memo/hide").status_code == 200
    pipeline.run(days=[DAY], publish=False, log=lambda *_: None)
    assert not item_file.exists()
    assert note.read_text() == "사용자의 메모"
    assert json.loads((folder / "보고서.json").read_text())["items"] == []
    assert "- [ ]" not in (folder / "할일.md").read_text()


def test_assets_are_copied_and_source_remains_intact(home):
    from PIL import Image
    config.update_settings({"llm": {"backend": "fake"}})
    data = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(data, "PNG")
    _, item = import_share({"id": "photo", "ts": f"{DAY}T10:05:00+09:00", "kind": "image", "name": "캡처.png",
                           "mime": "image/png"}, data.getvalue(), 4)
    pipeline.run(publish=False, log=lambda *_: None)
    original = config.MEDIA / item["media"]
    copy = next((archive.day_dir(DAY) / "원본").iterdir())
    assert original.read_bytes() == copy.read_bytes() == data.getvalue()
    src = re.search(r'<img src="([^"]+)"', (archive.day_dir(DAY) / "보고서.html").read_text()).group(1)
    assert app.test_client().get(f"/reports/{DAY}/{src}").data == data.getvalue()


def test_untrusted_text_urls_paths_and_csv_are_safe(home):
    memo(home)
    row = store.get_digest(DAY)
    data = row["data"]
    item = data["items"][0]
    data["read_later"] = [item["id"]]
    item.update({"title": '=HYPERLINK("malicious")', "summary": '<script>alert("bad")</script>',
                 "category": "../../별도폴더", "url": "https://example.com/test", "media": "../../private.txt"})
    store.save_digest(DAY, data, "safety-fixture")
    archive.export_day(DAY)
    folder = archive.day_dir(DAY)
    assert "<script>" not in (folder / "보고서.html").read_text()
    assert "&lt;script&gt;" in (folder / "보고서.html").read_text()
    rows = list(csv.reader(io.StringIO((folder / "링크.csv").read_text("utf-8-sig"))))
    assert rows[1][2].startswith("'=")
    assert all(p.resolve().is_relative_to(folder.resolve()) for p in folder.rglob("*"))
    assert not (folder / "원본").exists()
    item["url"] = "javascript:alert(1)"
    store.save_digest(DAY, data, "bad-url")
    archive.export_day(DAY)
    assert "javascript:" not in (folder / "보고서.html").read_text()
    assert "javascript:" not in (folder / "보고서.md").read_text()
    assert app.test_client().get(f"/reports/{DAY}/../{DAY}/.haru-files.json").status_code == 404
    with pytest.raises(ValueError):
        archive.export_day("../../outside")


@pytest.mark.parametrize("nested", [False, True])
def test_inbox_never_reimports_generated_reports(home, nested):
    if nested:
        config.update_settings({"archive": {"directory": str(config.INBOX / "成果" / "정리")}})
    memo(home)
    before = len(store.recent_imports())
    errors = []
    assert inbox.scan(config.load_settings(), log=errors.append) == []
    assert not errors and len(store.recent_imports()) == before
    assert (archive.day_dir(DAY) / "보고서.html").exists()
