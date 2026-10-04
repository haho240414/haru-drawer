"""AI 사슬: Codex 사용 한도 → 쉬는 시간 기록 → 로컬 모델(ollama)로 대신 → 둘 다 안 되면 규칙 기반 → 다시 되면 재분석."""
from datetime import datetime

import pytest

from conftest import FIX
from haru import config, llm, store


def test_parse_retry_at():
    now = datetime(2026, 10, 2, 1, 0).timestamp()
    t = datetime.fromtimestamp(llm.parse_retry_at("ERROR: ... try again at 3:11 AM.", now))
    assert (t.hour, t.minute) == (3, 12) and t.day == 2
    t = datetime.fromtimestamp(llm.parse_retry_at("try again at 12:05 AM", now))
    assert t.day == 3 and t.hour == 0      # 지난 시각이면 다음 날
    assert llm.parse_retry_at("알 수 없는 오류", now) == now + 1800
    assert llm.parse_retry_at("try again at 99:99 AM", now) == now + 1800


@pytest.fixture()
def ai(home, monkeypatch):
    """Codex·ollama 호출을 가짜로 바꾸고 몇 번 불렸는지 센다."""
    calls = {"codex": 0, "ollama": 0}
    state = {"codex_quota": False, "ollama_ok": True}

    def answer(prompt, backend):
        import re
        refs = re.findall(r"\[(A\d+)\]", prompt)
        if refs:
            return {"items": [{"ref": r, "category": "AI·테크", "title": f"{backend} 제목", "summary": "요약",
                               "quick_summary": ["핵심 주장", "근거", "확인할 점"], "briefing": [{"heading": "설명", "body": "자료의 내용"}],
                               "key_points": [], "intent": "참고 자료", "actions": [], "tags": [], "importance": 3,
                               "lock_line": "한 줄"} for r in refs], "_llm": {"backend": backend}}
        return {"headline": f"{backend} 헤드라인", "summary": "s", "quick_summary": ["핵심", "근거", "조건"], "highlights": [], "themes": [], "todos": [],
                "read_later": [], "lock": {"title": "t", "lines": []}, "tomorrow": "", "_llm": {"backend": backend}}

    def fake_codex(prompt, schema, images=(), **kw):
        calls["codex"] += 1
        if state["codex_quota"]:
            raise llm.LLMQuotaError("Codex 사용 한도", 9_999_999_999)
        return answer(prompt, "codex")

    def fake_ollama(prompt, schema, images=(), **kw):
        calls["ollama"] += 1
        if not state["ollama_ok"]:
            raise llm.LLMError("ollama 꺼짐")
        return answer(prompt, "ollama")

    monkeypatch.setattr(llm, "run_codex", fake_codex)
    monkeypatch.setattr(llm, "run_ollama", fake_ollama)
    from haru import pipeline
    monkeypatch.setattr(pipeline, "enrich_link", lambda url: {"title": "제목", "site_kind": "web", "site": "웹"})
    config.update_settings({"llm": {"backend": "codex", "fallback": "ollama"}})
    return calls, state


def test_quota_falls_back_to_ollama_and_cools_down(ai):
    calls, state = ai
    s = config.load_settings()
    state["codex_quota"] = True
    out = llm.run_json("[A1] 메모", {"type": "object", "properties": {}}, settings=s)
    assert out["_llm"]["backend"] == "ollama" and calls == {"codex": 1, "ollama": 1}
    assert store.kv_get("llm_cooldown_codex")["until"] > 0
    # 쉬는 동안은 Codex 를 아예 안 부른다
    llm.run_json("[A1] 메모", {"type": "object", "properties": {}}, settings=s)
    assert calls["codex"] == 1 and calls["ollama"] == 2
    assert llm.batch_size(s) == 3              # 로컬 모델은 작은 묶음


def test_all_down_uses_heuristic_then_upgrades(ai, monkeypatch):
    from haru import pipeline, timeutil
    from haru.inbox import import_any
    calls, state = ai
    s = config.load_settings()
    state["codex_quota"] = True
    state["ollama_ok"] = False
    import_any(FIX / "android_self.txt", s)
    pipeline.run(publish=False)
    items = [i for i in store.items_for_day("2026-10-01") if i["kind"] == "link"]
    assert all(i["analysis"]["source"] == "heuristic" for i in items)
    assert store.get_digest("2026-10-01")["data"]["llm"]["backend"] == "heuristic"
    # 한도가 풀리면(쉬는 시간 끝) 다음 정리에서 최근 사흘의 규칙 기반 항목·보고서를 AI 로 다시
    store.kv_set("llm_cooldown_codex", {"until": 0})
    state["codex_quota"] = False
    monkeypatch.setattr(timeutil, "today", lambda b=4: "2026-10-01")
    pipeline.run(publish=False)
    items = [i for i in store.items_for_day("2026-10-01") if i["kind"] == "link"]
    assert all(i["analysis"]["source"] == "codex" for i in items), [i["analysis"]["source"] for i in items]
    assert store.get_digest("2026-10-01")["data"]["llm"]["backend"] == "codex"
    # 이미 AI 로 바뀐 건 다시 돌리지 않는다
    n = calls["codex"]
    pipeline.run(publish=False)
    assert calls["codex"] == n


def test_all_down_does_not_repeat_failed_requests(ai, monkeypatch):
    from haru import pipeline, timeutil
    from haru.inbox import import_any
    calls, state = ai
    state.update(codex_quota=True, ollama_ok=False)
    monkeypatch.setattr(timeutil, "today", lambda b=4: "2026-10-01")
    import_any(FIX / "android_self.txt", config.load_settings())
    pipeline.run(publish=False)
    assert calls == {"codex": 1, "ollama": 1}
    version = store.get_digest("2026-10-01")["version"]
    pipeline.run(publish=False)
    assert calls == {"codex": 1, "ollama": 1}
    assert store.get_digest("2026-10-01")["version"] == version
    # 로컬 모델이 먼저 복구되면 Codex 한도 중에도 AI 로 정리한다.
    store.kv_set("llm_cooldown_ollama", {"until": 0})
    state["ollama_ok"] = True
    pipeline.run(publish=False)
    assert store.get_digest("2026-10-01")["data"]["llm"]["backend"] == "ollama"
    assert calls["codex"] == 1


def test_repeated_link_does_not_reuse_heuristic_when_ai_recovers(ai):
    from haru.analyze import analyze_items, heuristic_item
    s = config.load_settings()
    old = {"id": "old", "day": "2026-09-20", "ts": "2026-09-20T10:00:00+09:00",
           "source": "share", "kind": "link", "url": "https://example.com/article",
           "url_key": "same-link", "text": "자료", "meta": {"title": "자료"}}
    store.upsert_item(old)
    store.update_item("old", analysis=heuristic_item(old, s["categories"]), status="analyzed")
    new = {**old, "id": "new", "day": "2026-10-01", "ts": "2026-10-01T10:00:00+09:00"}
    store.upsert_item(new)
    store.update_item("new", status="enriched")
    analyze_items([store.get_item("new")], s)
    assert store.get_item("new")["analysis"]["source"] == "codex"


def test_old_brief_analysis_is_upgraded_then_detailed_analysis_is_reused(ai):
    from haru.analyze import SUMMARY_VERSION, analyze_items
    calls, _ = ai
    settings = config.load_settings()
    item = {"id": "brief", "day": "2026-09-20", "ts": "2026-09-20T10:00:00+09:00",
            "source": "share", "kind": "link", "url": "https://example.com/detail",
            "url_key": "detail-link", "meta": {"title": "원문"}}
    store.upsert_item(item)
    store.update_item("brief", status="analyzed", analysis={"source": "codex", "summary": "이전 짧은 요약"})
    store.db().execute("UPDATE items SET updated_at=? WHERE id='brief'", ("2026-09-20T10:00:00+09:00",))
    for ident, day in (("expanded", "2026-10-01"), ("repeated", "2026-10-02")):
        store.upsert_item({**item, "id": ident, "day": day, "ts": f"{day}T10:00:00+09:00"})
        store.update_item(ident, status="enriched")
        analyze_items([store.get_item(ident)], settings)
    expanded = store.get_item("expanded")["analysis"]
    repeated = store.get_item("repeated")["analysis"]
    assert expanded["summary_version"] == SUMMARY_VERSION
    assert expanded["summary"] != "이전 짧은 요약"
    assert repeated["reused_from"] == "expanded"
    assert calls["codex"] == 1


@pytest.mark.parametrize("reply", ['{"broken":', '[]', 'null'])
def test_malformed_codex_reply_falls_back(home, monkeypatch, reply):
    from pathlib import Path
    from types import SimpleNamespace
    monkeypatch.setattr(llm, "find_codex", lambda: "codex")

    def run(cmd, **kw):
        Path(cmd[cmd.index("-o") + 1]).write_text(reply)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(llm.subprocess, "run", run)
    monkeypatch.setattr(llm, "run_ollama", lambda *a, **kw: {"ok": True, "_llm": {"backend": "ollama"}})
    result = llm.run_json("메모", {"type": "object", "properties": {}}, settings=config.load_settings(), retries=0)
    assert result["_llm"]["backend"] == "ollama"
