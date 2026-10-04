"""빠른 브리핑과 전체 내용 자료의 분리·완전성·전송 호환을 검증한다."""
import json

import pytest

from haru import archive, config, store, transcribe
from haru.analyze import build_digest
from haru.briefing import validate_item, validate_quick
from haru.llm import LLMError
from haru.pipeline import build_bundle


@pytest.mark.parametrize("lines", [[], ["한 줄"], ["첫째", "둘째", ""], ["1", "2", "3", "4"]])
def test_incomplete_three_lines_are_rejected(lines):
    with pytest.raises(LLMError):
        validate_quick({"quick_summary": lines})


def test_briefing_cannot_be_empty():
    with pytest.raises(LLMError):
        validate_item({"quick_summary": ["주장", "근거", "조건"], "briefing": []})


def test_even_short_full_transcript_has_source_material_and_reuses_it(home):
    text = "[00:00:00–00:00:30] 세전 수입 250만원.\n[00:00:30–00:01:00] 비용은 별도이며 마지막 결론은 비교 필요."
    item = {"id": "short", "meta": {"transcript": text, "content_basis": "audio_transcript"}}
    calls = []
    def ai(prompt, *args):
        calls.append(prompt)
        return {"summary": "수입과 비용", "points": ["세전 250만원"], "uncertain": [], "sections": [
            {"heading": "수입 공개", "time": "00:00:00–00:00:30", "body": "제작자가 세전 수입 250만원을 설명한다."},
            {"heading": "비용과 마지막 결론", "time": "00:00:30–00:01:00", "body": "비용은 별도이며 비교가 필요하다고 설명한다."}]}
    meta = transcribe.prepare_notes(item, {}, ai)
    assert meta["transcript_notes_complete"] and len(calls) == 1
    assert meta["transcript_notes"][0]["source_chars"] == len(text)
    assert meta["transcript_notes"][0]["source_range"] == "00:00:00–00:01:00"
    assert "마지막 결론" in calls[0]
    again = transcribe.prepare_notes(dict(item, meta=meta), {}, ai)
    assert again == meta and len(calls) == 1


def test_missing_source_sections_are_not_success(home):
    item = {"id": "short", "meta": {"transcript": "확인한 음성", "content_basis": "full_transcript"}}
    with pytest.raises(LLMError):
        transcribe.prepare_notes(item, {}, lambda *a: {"summary": "핵심만", "points": [], "sections": []})


def test_report_source_files_and_phone_bundle_keep_different_reading_depths(home):
    settings = config.update_settings({"llm": {"backend": "fake"}})
    item = {"id": "brief-source", "day": "2026-10-03", "ts": "2026-10-03T22:00:00+09:00", "source": "youtube",
            "kind": "link", "url": "https://www.youtube.com/watch?v=abcdefghijk", "meta": {
                "transcript": "[00:00:00] 원래 발언 전문", "content_basis": "audio_transcript",
                "transcript_notes_complete": True, "transcript_notes": [{"part": 1, "total": 1,
                    "sections": [{"heading": "후반 근거", "time": "00:00:00", "body": "상세 원본 내용 <script>"}],
                    "uncertain": ["단위 확인 필요"]}]}}
    store.upsert_item(item)
    store.update_item(item["id"], status="analyzed", analysis={"title": "완전한 브리핑", "summary": "짧은 설명",
        "quick_summary": ["핵심 주장", "주요 근거", "확인 조건"], "briefing": [{"heading": "논리와 사례", "body": "긴 설명과 구체적 사례"}]})
    digest = build_digest(item["day"], settings)
    folder = archive.export_day(item["day"], settings)
    report = (folder / "보고서.html").read_text()
    source = (folder / "원본내용정리.html").read_text()
    assert "3줄 요약" in report and "긴 설명과 구체적 사례" in report
    assert "원본내용정리.html#source-" in report and "상세 원본 내용" not in report
    assert "상세 원본 내용 &lt;script&gt;" in source and "단위 확인 필요" in source
    assert ".srt" not in source  # 시간 세그먼트가 없는 전문에는 없는 파일 링크를 만들지 않는다.
    manifest = json.loads((folder / archive.MANIFEST).read_text())["files"]
    assert {"원본내용정리.html", "원본내용정리.md"} <= manifest.keys()
    assert next((folder / "전문").glob("*.txt")).read_text().strip() == item["meta"]["transcript"]
    sent = json.loads(build_bundle(digest, {}))["digest"]["items"][0]
    assert sent["quick_summary"] == ["핵심 주장", "주요 근거", "확인 조건"]
    assert sent["briefing"][0]["body"] == "긴 설명과 구체적 사례"
    assert sent["transcript_sections"][0]["sections"][0]["body"] == "상세 원본 내용 <script>"


def test_reused_summary_also_keeps_complete_source_notes(home, monkeypatch):
    import hashlib
    from haru import analyze, llm
    s = config.load_settings()
    text = "[00:00:00] 전문의 마지막 결론"
    notes = [{"part": 1, "total": 1, "sections": [{"heading": "결론", "time": "00:00:00", "body": "완전한 정리"}]}]
    old = {"id": "old", "day": "2026-10-02", "ts": "2026-10-02T22:00:00+09:00", "source": "youtube",
           "kind": "link", "url": "https://www.youtube.com/watch?v=abcdefghijk", "url_key": "same", "meta": {
               "transcript": text, "content_basis": "audio_transcript", "transcript_notes": notes,
               "transcript_notes_complete": True,
               "transcript_notes_sig": hashlib.sha256(f"{transcribe.NOTES_VERSION}:{text}".encode()).hexdigest()}}
    store.upsert_item(old)
    store.update_item("old", status="analyzed", analysis={"source": "codex", "summary_version": analyze.SUMMARY_VERSION,
        "summary": "이전에 완성한 브리핑", "evidence_sig": transcribe.evidence_sig(old["meta"])})
    current = dict(old, id="current", day="2026-10-03", meta={"transcript": text, "content_basis": "audio_transcript",
                                                          "date_basis": "first_observed_at"})
    store.upsert_item(current)
    store.update_item("current", status="enriched")
    monkeypatch.setattr(llm, "available", lambda s: True)
    monkeypatch.setattr(analyze, "run_json", lambda *a: pytest.fail("완성한 자료를 재사용해야 함"))
    assert analyze.analyze_items([store.get_item("current")], s)["reused"] == 1
    meta = store.get_item("current")["meta"]
    assert meta["transcript_notes"] == notes and meta["date_basis"] == "first_observed_at"


def test_failed_source_file_save_is_not_daily_success(home, monkeypatch):
    from haru import pipeline
    config.update_settings({"llm": {"backend": "fake"}})
    store.upsert_item({"id": "day-note", "day": "2026-10-03", "ts": "2026-10-03T22:00:00+09:00", "source": "share", "kind": "text", "text": "메모"})
    def fail(*args):
        raise OSError("디스크 저장 실패")
    monkeypatch.setattr(archive, "export_day", fail)
    result = pipeline.run(days=["2026-10-03"], publish=False)
    assert not result["ok"] and result["export_errors"] == ["2026-10-03"]


def test_old_report_still_shows_its_summary_immediately():
    digest = {"day": "2026-10-03", "version": 1, "summary": "이전 하루 요약", "items": [
        {"id": "old", "title": "이전 자료", "summary": "이전 항목 요약"}]}
    html = archive._report_html(digest, {})
    assert "<p>이전 하루 요약</p>" in html and "<p>이전 항목 요약</p>" in html
    assert '<details class="briefing">' not in html and '오늘의 상세 브리핑' not in html
