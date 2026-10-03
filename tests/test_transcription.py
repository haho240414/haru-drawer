"""전문 끝까지 전달·전사 재사용·실패 재시도·전문 파일 보존을 검증한다."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from haru import config, store, transcribe
from haru.llm import LLMError

URL = "https://www.youtube.com/watch?v=abcdefghijk"


def settings(tmp_path):
    python = tmp_path / "python"
    python.write_text("worker")
    return {"transcription": {"enabled": True, "python": str(python), "model": "test-model"}}


def item(meta=None):
    return {"id": "test-transcript", "day": "2026-10-03", "kind": "link", "source": "youtube",
            "ts": "2026-10-03T22:00:00+09:00", "url": URL, "text": "", "status": "enriched",
            "meta": meta or {"site_kind": "video", "content_basis": "metadata_only"}}


def test_lossless_split_includes_ending_and_does_not_exceed_limit():
    text = "[00:00:00] 근거 설명 100만원.\n" * 2500 + "[01:59:59] 마지막 결론은 세전 250만원."
    parts = transcribe.split_transcript(text)
    assert len(parts) > 5 and "".join(parts) == text
    assert all(len(p) <= 10000 for p in parts)
    assert "마지막 결론은 세전 250만원" in parts[-1]


def test_transcription_cache_skips_download_and_preserves_timestamps(home, tmp_path, monkeypatch):
    s = settings(tmp_path)
    calls = []
    def worker(args, **kwargs):
        job = json.loads(Path(args[-1]).read_text())
        calls.append(job)
        transcribe._write_json(Path(job['output']), {
            "complete": True, "video_id": "abcdefghijk", "language": "ko", "expected_seconds": 120,
            "processed_seconds": 120, "segments": [{"start": 0, "end": 120, "text": "마지막 결론"}]})
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(transcribe.subprocess, "run", worker)
    first = transcribe.ensure_transcript(URL, {}, s)
    again = transcribe.ensure_transcript(URL, {}, s)
    assert first == again and len(calls) == 1
    assert first["content_basis"] == "audio_transcript" and "00:02:00" in first["transcript"]
    assert first["transcription_pending"] is False
    assert transcribe.srt(first["transcript_segments"]).startswith("1\n00:00:00,000 --> 00:02:00,000")


def test_timeout_is_not_full_transcript_success(home, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("worker", 1)
    monkeypatch.setattr(transcribe.subprocess, "run", fail)
    with pytest.raises(transcribe.TranscriptionError, match="미완료"):
        transcribe.ensure_transcript(URL, {}, settings(tmp_path))
    assert not list((config.DATA / "transcripts").glob("*.job.json"))


def test_no_recognized_speech_does_not_invent_a_transcript_or_loop(home, tmp_path, monkeypatch):
    def worker(args, **kwargs):
        job = json.loads(Path(args[-1]).read_text())
        transcribe._write_json(Path(job["output"]), {"complete": True, "video_id": "abcdefghijk",
            "segments": [], "no_speech": True, "processed_seconds": 120, "expected_seconds": 120})
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(transcribe.subprocess, "run", worker)
    result = transcribe.ensure_transcript(URL, {}, settings(tmp_path))
    assert result["content_basis"] == "audio_no_speech" and not result.get("transcript")
    assert result["transcription_status"] == "ready" and "인식하지 못했어요" in result["note"]
    monkeypatch.setattr(transcribe.subprocess, "run", lambda *a, **k: pytest.fail("캐시가 재사용되어야 함"))
    assert transcribe.ensure_transcript(URL, {}, settings(tmp_path)) == result


def test_pending_error_remains_retryable_and_hidden_item_is_skipped(home, monkeypatch):
    # 저장소의 실제 항목 형식을 써서 실패해도 이전 분석은 보존되는지 확인한다.
    it = item()
    it["meta"] = {"site_kind": "video", "transcription_pending": True}
    store.upsert_item(it)
    store.update_item(it["id"], status="analyzed", analysis={"summary": "이전 보고서"})
    def fail(*args):
        raise transcribe.TranscriptionError("음성 접속 실패")
    monkeypatch.setattr(transcribe, "ensure_transcript", fail)
    result = transcribe.pending({"transcription": {"enabled": True}}, lambda _: None)
    row = store.get_item(it["id"])
    assert result["errors"] and row["meta"]["transcription_pending"]
    assert row["analysis"]["summary"] == "이전 보고서"
    monkeypatch.setattr(transcribe, "ensure_transcript", lambda *a: {
        "transcription_pending": False, "content_basis": "audio_transcript", "transcript": "전체 전문"})
    assert transcribe.pending({"transcription": {"enabled": True}}, lambda _: None)["completed"] == 1
    assert store.get_item(it["id"])["status"] == "enriched"
    store.update_item(it["id"], status="hidden")
    assert transcribe.queue_day("2026-10-03") == 0


def test_long_transcript_all_parts_reach_item_prompt(home):
    from haru.enrich import summarize_meta_for_prompt
    text = "근거 설명과 수치 10만원.\n" * 1700 + "마지막 결론은 250만원."
    it = item({"transcript": text, "content_basis": "audio_transcript"})
    calls = []
    def ai(prompt, *args):
        calls.append(prompt)
        return {"summary": "구간 요약", "points": ["마지막 결론 250만원" if "마지막 결론은" in prompt else "수치 10만원"], "uncertain": []}
    meta = transcribe.prepare_notes(it, {}, ai)
    assert len(calls) == len(transcribe.split_transcript(text)) > 2
    assert "마지막 결론은 250만원" in calls[-1]
    prompt = json.loads(summarize_meta_for_prompt(meta))
    assert "250만원" in prompt["전문 전체의 구간별 정리"][-1]["points"][0]
    assert meta["transcript_notes_complete"]
    assert transcribe.prepare_notes(dict(it, meta=meta), {}, ai) == meta
    assert len(calls) == len(meta["transcript_notes"])


def test_notes_checkpoint_resumes_only_unfinished_parts(home, monkeypatch):
    it = item()
    it["meta"] = {"transcript": "음성 원문\n" * 6000, "content_basis": "audio_transcript"}
    store.upsert_item(it)
    calls = []
    def ai(prompt, *args):
        calls.append(prompt)
        if len(calls) == 2:
            raise LLMError("한도")
        return {"summary": "확인한 주장", "points": ["근거"], "uncertain": []}
    with pytest.raises(LLMError):
        transcribe.prepare_notes(it, {}, ai)
    saved = store.get_item(it["id"])
    assert len(saved["meta"]["transcript_notes"]) == 1 and not saved["meta"]["transcript_notes_complete"]
    completed = transcribe.prepare_notes(saved, {}, ai)
    assert completed["transcript_notes_complete"] and "2/" in calls[2]


def test_shorter_replacement_transcript_drops_stale_notes(home):
    from haru.enrich import summarize_meta_for_prompt
    meta = {"transcript": "새롭게 확인한 음성 원문", "content_basis": "audio_transcript",
            "transcript_notes_sig": "old", "transcript_notes_complete": True,
            "transcript_notes": [{"summary": "이전 영상의 다른 내용"}]}
    updated = transcribe.prepare_notes(item(meta), {}, lambda *a: pytest.fail("짧은 원문은 직접 읽음"))
    assert "transcript_notes" not in updated
    prompt = summarize_meta_for_prompt(updated)
    assert "새롭게 확인한 음성 원문" in prompt and "이전 영상" not in prompt


def test_provider_captions_are_not_truncated(home, monkeypatch):
    import yt_dlp
    from haru import enrich
    class YDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, *args, **kwargs):
            return {"title": "시험 영상", "subtitles": {"ko": [{"ext": "json3", "url": "https://example.com/sub"}]}}
    class Response:
        ok = True
        def json(self):
            return {"events": [{"tStartMs": n*1000, "dDurationMs": 1000, "segs": [{"utf8": "설명\n" * 50}]} for n in range(200)] +
                              [{"tStartMs": 200000, "dDurationMs": 1000, "segs": [{"utf8": "마지막 결론 250만원"}]}]}
    monkeypatch.setattr(yt_dlp, "YoutubeDL", YDL)
    monkeypatch.setattr(enrich.requests, "get", lambda *a, **kw: Response())
    meta = enrich.fetch_youtube(URL)
    assert len(meta["transcript"]) > 16000 and meta["transcript"].endswith("마지막 결론 250만원")
    assert meta["content_basis"] == "full_transcript" and len(meta["transcript_segments"]) == 201


def test_archive_keeps_full_text_srt_and_all_sections(home):
    from haru import archive
    from haru.analyze import build_digest
    s = config.update_settings({"llm": {"backend": "fake"}})
    it = item({"transcript": "[00:00:00–00:02:00] 最後 <script> 発言",
               "content_basis": "audio_transcript", "transcript_segments": [
                   {"start": 0, "end": 120, "text": "最後 <script> 発言"}],
               "transcript_notes_complete": True, "transcript_notes": [
                   {"part": 1, "total": 1, "summary": "마지막 <script> 결론", "points": ["250만원"], "uncertain": ["숫자 확인"]}]})
    store.upsert_item(it)
    store.update_item(it["id"], status="analyzed", analysis={"title": "영상", "summary": "전체 요약"})
    build_digest(it["day"], s)
    folder = archive.export_day(it["day"], s)
    assert next((folder / "전문").glob("*.txt")).read_text().strip() == it["meta"]["transcript"]
    assert "00:02:00,000" in next((folder / "전문").glob("*.srt")).read_text()
    html = (folder / "보고서.html").read_text()
    assert "영상 전체 구간별 정리" in html and "마지막 &lt;script&gt; 결론" in html
    assert "시간 표시 전문 받기" in html and "숫자 확인" in html


def test_new_transcript_cannot_reuse_an_old_metadata_summary(home, monkeypatch):
    from haru import analyze, llm
    s = config.load_settings()
    old = dict(item(), id="old-source", url_key="same-video")
    store.upsert_item(old)
    store.update_item(old["id"], status="analyzed", analysis={"title": "제목만", "summary": "옛 요약",
        "source": "codex", "summary_version": analyze.SUMMARY_VERSION})
    current = dict(item({"transcript": "마지막 근거: 세전 250만원", "content_basis": "audio_transcript"}),
                   id="new-source", url_key="same-video")
    store.upsert_item(current)
    store.update_item(current["id"], status="enriched")
    prompts = []
    def ai(prompt, *args):
        prompts.append(prompt)
        return {"items": [{"ref": "A1", "title": "실제 내용", "summary": "세전 250만원", "category": "재테크·투자"}],
                "_llm": {"backend": "codex"}}
    monkeypatch.setattr(llm, "available", lambda s: True)
    monkeypatch.setattr(analyze, "run_json", ai)
    result = analyze.analyze_items([store.get_item(current["id"])], s, lambda _: None)
    assert result["ai"] == 1 and not result.get("reused")
    assert "세전 250만원" in prompts[0] and store.get_item(current["id"])["analysis"]["summary"] != "옛 요약"


def test_pipeline_transcription_failure_is_not_success(home, monkeypatch):
    from haru import pipeline
    s = config.update_settings({"llm": {"backend": "fake"}, "transcription": {"enabled": True}})
    it = item()
    store.upsert_item(it)
    store.update_item(it["id"], status="enriched")
    def fail(*args):
        raise transcribe.TranscriptionError("로그인 제한")
    monkeypatch.setattr(transcribe, "ensure_transcript", fail)
    result = pipeline.run(days=[it["day"]], publish=False, log=lambda _: None)
    assert not result["ok"] and result["transcription"]["errors"]
    assert store.get_item(it["id"])["meta"]["transcription_pending"]
