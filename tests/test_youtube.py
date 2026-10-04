"""YouTube 새 저장분의 날짜·중복·오류·읽기 전용 연결과 기존 보고서 전달 검증."""
import json
import stat
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from haru import config, store, youtube

ECON = {"id": "PL_test_economy", "name": "경제", "topic": "경제"}
AI = {"id": "PL_test_ai_list", "name": "AI", "topic": "AI"}
REST = {"id": "PL_test_rest_list", "name": "휴식", "topic": "휴식"}
CLIENT = {"installed": {"client_id": "test.apps.googleusercontent.com", "client_secret": "test-client-secret"}}


def test_detail_prompt_preserves_evidence_beyond_the_old_excerpt():
    from haru.enrich import summarize_meta_for_prompt
    transcript = "배경 설명. " * 700 + "마지막 사례: 1인당 250만원이며 세전 기준이다."
    prompt = json.loads(summarize_meta_for_prompt({"title": "사례 비교", "transcript": transcript,
                                                  "content_basis": "partial_transcript"}))
    assert "250만원이며 세전 기준" in prompt["본문(일부)"]
    assert prompt["content_basis"] == "partial_transcript"


@pytest.fixture()
def cfg(home, monkeypatch):
    s = config.update_settings({"timezone": "Asia/Seoul", "llm": {"backend": "fake"},
                                "youtube": {"enabled": True, "playlists": [ECON, AI, REST]}})
    monkeypatch.setattr(youtube, "now", lambda: datetime.fromisoformat("2026-10-02T22:00:00+09:00"))
    return s


def entry(key="entry1", vid="abcdefghijk", at="2026-10-02T03:00:00Z", title="금리 전망"):
    return {"id": key, "snippet": {"publishedAt": at, "title": title, "description": "제작자가 소개하는 금리 관련 영상",
                                    "videoOwnerChannelTitle": "시험 채널", "resourceId": {"videoId": vid}},
            "contentDetails": {"videoId": vid, "videoPublishedAt": "2020-01-01T00:00:00Z"}}


def test_bootstrap_uses_saved_time_not_upload_time_and_skips_history(cfg):
    rows = [entry(), entry("old", "oldvideo123", "2025-01-01T00:00:00Z"),
            entry("night", "nightvideo1", "2026-10-01T18:00:00Z")]
    result = youtube._import_playlist(ECON, rows, cfg)
    assert result["new"] == 1 and result["skipped"] == 2
    item = store.items_for_day("2026-10-02")[0]
    assert item["ts"] == "2026-10-02T12:00:00+09:00"
    assert item["source"] == "youtube" and item["meta"]["date_basis"] == "playlist_added_at"
    assert youtube._import_playlist(ECON, rows, cfg)["new"] == 0


def test_incremental_catches_sleep_gap_and_respects_day_boundary(cfg):
    youtube._import_playlist(ECON, [], cfg)
    rows = [entry("missed", at="2026-10-01T18:00:00Z"), entry("ancient", "oldvideo123", "2026-09-01T00:00:00Z")]
    result = youtube._import_playlist(ECON, rows, cfg)
    assert result["new"] == 1 and result["days"] == ["2026-10-01"]  # 새벽 03시는 전날
    assert youtube._import_playlist(ECON, rows, cfg)["new"] == 0


def test_multi_playlist_video_is_once_per_day_and_hidden_stays_hidden(cfg):
    assert youtube._import_playlist(ECON, [entry()], cfg)["new"] == 1
    assert youtube._import_playlist(AI, [entry("ai-entry")], cfg)["updated"] == 1
    item = store.items_for_day("2026-10-02")[0]
    assert [p["name"] for p in item["meta"]["youtube_playlists"]] == ["경제", "AI"]
    store.update_item(item["id"], status="hidden")
    youtube._import_playlist(REST, [entry("rest-entry")], cfg)
    assert store.items_for_day("2026-10-02") == []
    assert store.get_item(item["id"])["status"] == "hidden"


def test_same_video_saved_another_day_is_a_new_daily_interest(cfg):
    youtube._import_playlist(ECON, [entry()], cfg)
    youtube._import_playlist(AI, [], cfg)
    youtube._import_playlist(AI, [entry("different-day", at="2026-10-01T03:00:00Z")], cfg)
    assert len(store.items_for_day("2026-10-01")) == len(store.items_for_day("2026-10-02")) == 1


def test_bad_or_incomplete_playlist_keeps_baseline_and_other_sources(cfg, monkeypatch):
    youtube._import_playlist(ECON, [], cfg)
    before = store.kv_get("youtube_seen:" + ECON["id"])
    bad = entry("missing-saved-time")
    del bad["snippet"]["publishedAt"]
    monkeypatch.setattr(youtube, "_access_token", lambda: "fake-access")
    def fetch(resource, token, **params):
        return [entry(), bad] if params["playlistId"] == ECON["id"] else [entry("other", "otherabc123")]
    monkeypatch.setattr(youtube, "_pages", fetch)
    result = youtube.sync(cfg, lambda _: None)
    assert result["new"] == 1 and len(result["errors"]) == 1
    assert store.kv_get("youtube_seen:" + ECON["id"]) == before
    assert store.get_item("y:2026-10-02:abcdefghijk") is None


def test_pagination_failure_never_returns_partial_success(home, monkeypatch):
    class Response:
        ok = True
        def json(self):
            return {"items": [entry()], "nextPageToken": "repeated"}
    monkeypatch.setattr(youtube.requests, "get", lambda *a, **kw: Response())
    with pytest.raises(youtube.YouTubeError, match="전체"):
        youtube._pages("playlistItems", "test-access", playlistId=ECON["id"])


def test_watch_later_unsupported_and_selection_validated(home):
    with pytest.raises(youtube.YouTubeError, match="나중에 볼"):
        youtube.save_selection([{"id": "https://www.youtube.com/playlist?list=WL"}], True)
    with pytest.raises(youtube.YouTubeError):
        youtube.playlist_id("https://example.com/?list=PL_test_economy")
    saved = youtube.save_selection([ECON, ECON, REST], True)
    assert saved["youtube"]["playlists"] == [ECON, REST]


def test_oauth_pkce_readonly_state_one_use_and_private_tokens(home, monkeypatch):
    youtube.configure_client(CLIENT)
    auth_url = youtube.begin_auth(8892)
    q = parse_qs(urlsplit(auth_url).query)
    assert q["scope"] == [youtube.SCOPE] and q["code_challenge_method"] == ["S256"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8892/api/youtube/oauth/callback"]
    pending = youtube._read_auth()["pending"]
    calls = []
    def exchange(params):
        calls.append(params)
        return {"access_token": "private-access", "refresh_token": "private-refresh", "expires_in": 3600}
    monkeypatch.setattr(youtube, "_token_request", exchange)
    with pytest.raises(youtube.YouTubeError):
        youtube.finish_auth("bad-state", "code")
    youtube.finish_auth(q["state"][0], "code")
    assert calls[0]["code_verifier"] == pending["verifier"]
    with pytest.raises(youtube.YouTubeError):
        youtube.finish_auth(q["state"][0], "code")
    assert stat.S_IMODE(youtube._auth_path().stat().st_mode) == 0o600
    from haru.server import app
    with app.test_client() as c:
        for path in ("/api/youtube", "/api/settings", "/api/status"):
            body = c.get(path).data
            assert b"private-access" not in body and b"private-refresh" not in body and b"test-client-secret" not in body
        assert c.post("/api/youtube/disconnect", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert c.post("/api/youtube/disconnect", data="{}", content_type="text/plain").status_code == 415
    youtube.disconnect()
    assert not youtube.status()["connected"] and not config.load_settings()["youtube"]["enabled"]


def test_oauth_cancel_expiry_and_refresh(home, monkeypatch):
    youtube.configure_client(CLIENT)
    youtube.begin_auth(8892)
    pending = youtube._read_auth()["pending"]
    with pytest.raises(youtube.YouTubeError, match="취소"):
        youtube.finish_auth(pending["state"], "", denied=True)
    auth = youtube._read_auth()
    auth["token"] = {"refresh_token": "refresh-stays", "access_token": "expired", "expires_at": 0}
    youtube._write_auth(auth)
    monkeypatch.setattr(youtube, "_token_request", lambda p: {"access_token": "new-access", "expires_in": 3600})
    assert youtube._access_token() == "new-access"
    assert youtube._read_auth()["token"]["refresh_token"] == "refresh-stays"


def test_rest_context_and_transcript_limits_survive_reused_analysis(cfg):
    from haru.analyze import youtube_context, _describe
    youtube._import_playlist(REST, [entry(title="휴식 음악")], cfg)
    item = store.items_for_day("2026-10-02")[0]
    previous = {"summary": "편안한 음악", "actions": ["집중 업무 시작"], "category": "업무", "importance": 5}
    result = youtube_context(item, previous)
    assert result["category"] == "휴식" and result["actions"] == [] and result["importance"] == 2
    assert "자막 확인 불가" in result["summary"] and previous["actions"]
    assert "유튜브 저장 목록" in _describe("A1", item, None)
    item["meta"]["transcript"] = "일부 자막"
    assert "자막 확인 불가" not in youtube_context(item, previous)["summary"]


def test_youtube_pipeline_report_archive_and_phone_bundle(cfg, monkeypatch):
    from haru import pipeline
    from haru.relay import new_pairing, Relay
    from PIL import Image
    import sys
    from conftest import ROOT
    sys.path.insert(0, str(ROOT / "tools"))
    import mock_ntfy
    httpd, url = mock_ntfy.start()
    mock_ntfy.STORE.msgs.clear()
    mock_ntfy.STORE.files.clear()
    try:
        pair = new_pairing(url)
        cfg = config.update_settings({"relay": pair})
        phone = Relay(url, pair["up"], pair["down"], pair["key"])
        monkeypatch.setattr(youtube, "_access_token", lambda: "test-access")
        videos = {ECON["id"]: entry(), AI["id"]: entry("ai", "aitest12345", title="AI 활용"),
                  REST["id"]: entry("rest", "resttest123", title="휴식 음악")}
        monkeypatch.setattr(youtube, "_pages", lambda r, t, **p: [videos[p["playlistId"]]])
        monkeypatch.setattr(pipeline, "enrich_link", lambda url: {"content_basis": "metadata_only", "title": "", "description": ""})
        def cards(digest, settings):
            files = {}
            for style in ("A", "B"):
                p = config.CARDS / f"test_{style}.png"
                Image.new("RGBA", (100, 200)).save(p)
                files[style] = p
            return files
        monkeypatch.setattr("haru.lockcard.render_for_digest", cards)
        result = pipeline.run(publish=True, log=lambda _: None)
        assert result["youtube"]["new"] == 3 and result["published"] == ["2026-10-02"]
        digest = store.get_digest("2026-10-02")["data"]
        assert {i["category"] for i in digest["items"]} == {"재테크·투자", "AI·테크", "휴식"}
        assert all("자막 확인 불가" in i["summary"] for i in digest["items"])
        assert "금리 전망" in [i["title"] for i in digest["items"]]  # enrich 실패도 API 제목 보존
        archive = json.loads((config.INBOX / "정리/2026-10-02/보고서.json").read_text())
        assert archive["items"][0]["source"] == "youtube" and archive["items"][0]["youtube_playlists"]
        message = next(m for m in phone.poll(phone.down) if m.obj["t"] == "digest")
        bundle = json.loads(phone.fetch_attachment(message, phone.down))
        assert bundle["digest"]["stats"]["sources"] == {"youtube": 3}
        assert len(bundle["digest"]["lock"]["lines"]) <= 3
        assert pipeline.run(publish=True, log=lambda _: None)["published"] == []
    finally:
        httpd.shutdown()


def test_browser_baseline_then_new_observed_video_and_incomplete_keeps_history(cfg):
    cfg["youtube"]["mode"] = "browser"
    cfg["youtube"]["playlists"] = [ECON, {"id": "WL", "name": "나중에 볼 동영상", "topic": "기타"}]
    snapshot = {"source": "youtube_browser", "captured_at": "2026-10-02T22:00:00+09:00", "playlists": [
        {"id": ECON["id"], "complete": True, "reported_total": 1, "videos": [{"id": "abcdefghijk", "title": "오래된 영상"}]},
        {"id": "WL", "complete": True, "reported_total": 0, "videos": []}]}
    first = youtube.import_browser_snapshot(snapshot, cfg)
    assert first["baseline"] == 1 and first["new"] == 0 and store.items_for_day("2026-10-02") == []
    incomplete_empty = {"source": "youtube_browser", "captured_at": snapshot["captured_at"], "playlists": [
        {"id": ECON["id"], "complete": True, "reported_total": 1, "videos": []}]}
    assert youtube.import_browser_snapshot(incomplete_empty, cfg)["errors"]
    assert store.kv_get("youtube_browser_seen:" + ECON["id"])["ids"] == ["abcdefghijk"]
    snapshot["playlists"][0]["videos"] += [{"id": "aitest12345", "title": "새 저장 영상"}]
    snapshot["playlists"][0]["reported_total"] = 2
    snapshot["playlists"][0]["complete"] = False
    assert youtube.import_browser_snapshot(snapshot, cfg)["errors"]
    assert store.items_for_day("2026-10-02") == []
    snapshot["playlists"][0]["complete"] = True
    second = youtube.import_browser_snapshot(snapshot, cfg)
    assert second["new"] == 1
    item = store.items_for_day("2026-10-02")[0]
    assert item["meta"]["date_basis"] == "first_observed_at" and "saved_at" not in item["meta"]
    assert youtube.import_browser_snapshot(snapshot, cfg)["new"] == 0


def test_korean_22_schedule_runs_once_across_la_dst(home, monkeypatch):
    from zoneinfo import ZoneInfo
    cfg = config.update_settings({"youtube": {"mode": "browser", "enabled": True}})
    for month in (10, 11):
        slots = []
        for hour in (5, 6):
            local = datetime(2026, month, 3, hour, tzinfo=ZoneInfo("America/Los_Angeles"))
            monkeypatch.setattr(youtube, "now", lambda local=local: local)
            slots.append(youtube.browser_due(cfg)["due"])
        assert sum(slots) == 1
    at22 = datetime.fromisoformat("2026-11-03T22:00:00+09:00")
    monkeypatch.setattr(youtube, "now", lambda: at22)
    assert youtube.browser_due(cfg)["due"]
    youtube.browser_done()
    assert not youtube.browser_due(cfg)["due"]


def test_korean_midnight_schedule_runs_once_across_la_dst(home, monkeypatch):
    from zoneinfo import ZoneInfo
    cfg = config.update_settings({"youtube": {"mode": "browser", "enabled": True, "report_hour": 0}})
    for month in (10, 11):
        slots = []
        due_at = None
        for hour in (7, 8):
            local = datetime(2026, month, 3, hour, tzinfo=ZoneInfo("America/Los_Angeles"))
            monkeypatch.setattr(youtube, "now", lambda local=local: local)
            result = youtube.browser_due(cfg)
            slots.append(result["due"])
            if result["due"]:
                due_at = local
                assert result["day"] == f"2026-{month:02d}-04"
        assert sum(slots) == 1
        monkeypatch.setattr(youtube, "now", lambda: due_at)
        result = youtube.browser_due(cfg)
        youtube.browser_done(result["day"])
        assert not youtube.browser_due(cfg)["due"]


def test_browser_schedule_rejects_invalid_hour(home):
    for hour in (-1, 24, "0", True):
        with pytest.raises(youtube.YouTubeError):
            youtube.browser_due({"youtube": {"enabled": True, "mode": "browser", "report_hour": hour}})


def test_midnight_capture_belongs_to_the_previous_report_day(cfg, monkeypatch):
    monkeypatch.setattr(youtube, "now", lambda: datetime.fromisoformat("2026-10-05T00:05:00+09:00"))
    cfg["youtube"].update(mode="browser", report_hour=0, playlists=[ECON])
    snapshot = {"source": "youtube_browser", "captured_at": "2026-10-05T00:00:00+09:00", "playlists": [
        {"id": ECON["id"], "complete": True, "reported_total": 0, "videos": []}]}
    assert youtube.import_browser_snapshot(snapshot, cfg)["new"] == 0
    snapshot["captured_at"] = "2026-10-05T00:05:00+09:00"
    snapshot["playlists"][0].update(reported_total=1, videos=[{"id": "abcdefghijk", "title": "자정 새 영상"}])
    result = youtube.import_browser_snapshot(snapshot, cfg)
    assert result["new"] == 1 and result["days"] == ["2026-10-04"]
    assert store.items_for_day("2026-10-05") == []


def test_browser_done_after_midnight_keeps_the_collected_day(home, monkeypatch, capsys):
    from haru.__main__ import main
    cfg = config.update_settings({"youtube": {"mode": "browser", "enabled": True}})
    monkeypatch.setattr(youtube, "now", lambda: datetime.fromisoformat("2026-10-05T00:15:00+09:00"))
    assert main(["youtube", "done", "--day", "2026-10-04"]) == 0
    assert json.loads(capsys.readouterr().out)["day"] == "2026-10-04"
    assert store.kv_get("youtube_browser_daily_run")["day"] == "2026-10-04"
    monkeypatch.setattr(youtube, "now", lambda: datetime.fromisoformat("2026-10-05T22:00:00+09:00"))
    assert youtube.browser_due(cfg)["due"]  # 다음 날 예약을 잘못 건너뛰지 않는다.


def test_browser_done_rejects_invalid_future_and_regressive_days(home, monkeypatch):
    monkeypatch.setattr(youtube, "now", lambda: datetime.fromisoformat("2026-10-05T00:15:00+09:00"))
    for day in ("2026-10-06", "2026-02-30", "20261004", "2026-10-04/extra"):
        with pytest.raises(youtube.YouTubeError):
            youtube.browser_done(day)
        assert store.kv_get("youtube_browser_daily_run") is None
    youtube.browser_done("2026-10-04")
    previous = store.kv_get("youtube_browser_daily_run")
    with pytest.raises(youtube.YouTubeError):
        youtube.browser_done("2026-10-03")
    assert store.kv_get("youtube_browser_daily_run") == previous
