"""항목 분석(묶음) + 하루 보고서(다이제스트) 만들기.

AI 를 못 쓰면(코덱스 실패·시험 모드) 규칙 기반으로라도 같은 모양의 결과를 만든다 — 잠금화면이 비지 않게.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections import Counter
from pathlib import Path

from . import config, store
from .enrich import summarize_meta_for_prompt
from .ingest import bytes_to_jpeg
from .llm import LLMError, run_json
from .timeutil import day_label, iso, now, parse_iso, shift_day

INTENTS = ["나중에 읽기", "할 일", "구매 검토", "아이디어", "참고 자료", "일정", "기록", "기타"]
KIND_KO = {"link": "링크", "image": "캡처·사진", "text": "메모", "video": "동영상", "file": "파일", "audio": "음성"}


def item_schema(categories: list[str]) -> dict:
    return {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "ref": {"type": "string"},
        "category": {"type": "string", "enum": categories},
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "intent": {"type": "string", "enum": INTENTS},
        "actions": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
        "importance": {"type": "integer"},
        "lock_line": {"type": "string"},
    }}}}}


DIGEST_SCHEMA = {"type": "object", "properties": {
    "headline": {"type": "string"},
    "summary": {"type": "string"},
    "highlights": {"type": "array", "items": {"type": "object", "properties": {
        "ref": {"type": "string"}, "why": {"type": "string"}}}},
    "themes": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "refs": {"type": "array", "items": {"type": "string"}},
        "insight": {"type": "string"}}}},
    "todos": {"type": "array", "items": {"type": "object", "properties": {
        "text": {"type": "string"}, "ref": {"type": "string"},
        "when": {"type": "string", "enum": ["오늘", "이번 주", "언젠가"]}}}},
    "read_later": {"type": "array", "items": {"type": "string"}},
    "lock": {"type": "object", "properties": {
        "title": {"type": "string"}, "lines": {"type": "array", "items": {"type": "string"}}}},
    "tomorrow": {"type": "string"},
}}

ITEM_PROMPT = """너는 사용자의 '하루서랍' 비서다. 사용자는 카카오톡 '나에게 보내기'(나와의 채팅)로 링크·캡처·메모를 자기 자신에게 보내 모아 둔다.
아래는 그렇게 모은 항목들이다. 각 항목이 무엇인지, 사용자가 왜 보냈을지 분석하라.
사용자 소개: {profile}

항목마다 다음을 채운다:
- ref: 항목 번호 그대로 (예: "A3")
- category: 정해진 목록 중 하나
- title: 무엇인지 바로 알 수 있는 짧은 제목 (28자 이내, 사이트 이름·광고 문구·이모지 빼고 핵심만)
- summary: 핵심 내용 2~3문장. 링크 본문·캡처·메모에 실제로 있는 내용만 쓴다. 가격·날짜·수치·고유명사는 그대로 살린다.
- key_points: 기억할 포인트 0~3개 (각 40자 이내)
- intent: 왜 보냈을지 — {intents} 중 하나
- actions: 사용자가 실제로 할 만한 다음 행동 0~2개 (각 25자 이내, 구체적으로). 없으면 빈 배열.
- tags: 검색용 짧은 태그 0~4개
- importance: 1~5 (5 = 다시 꼭 봐야 함: 마감·가격·일정·돈이 걸린 결정 / 1 = 가벼운 참고)
- lock_line: 잠금화면용 한 줄 (18자 이내, 명사형으로 끝)

규칙:
- 링크 본문을 못 읽었으면(오류·로그인 벽·차단) 메시지 글과 미리보기만으로 판단하고 summary 끝에 "(본문 확인 불가)"를 붙인다. 없는 내용을 지어내지 않는다.
- 캡처 이미지는 화면 속 글자를 읽어 무엇인지 파악한다 (상품·매물·기사·대화·일정·코드·결제 등). 이미지 번호와 항목 번호의 짝을 지킨다.
- 사용자가 직접 쓴 메모는 메모 내용을 정리한다 (할 일이면 intent '할 일').
- 원본이 없는 사진·동영상 자리표시("사진", "동영상")는 '내용 확인 불가'로 짧게 처리하고 importance 1.
- 문장은 간결한 한국어 평서문·명사형. 존댓말·감탄·이모지 금지.

카테고리 목록: {categories}

항목들:
{items}
"""

DIGEST_PROMPT = """너는 사용자의 '하루서랍' 비서다. 사용자가 {label}에 카톡 '나에게 보내기'로 모은 {n}개 항목의 분석 결과로 하루 보고서를 쓴다.
사용자 소개: {profile}
최근 흐름: {trend}

쓸 것:
- headline: 그날을 한 줄로 (24자 이내, 무엇에 관심을 쏟은 날인지). 예: "회천 매물 비교하고 AI 자동화 파고든 날"
- summary: 3~4문장. 오늘 무엇에 관심이 몰렸는지, 항목들 사이의 연결점, 놓치면 안 될 것.
- highlights: 가장 중요한 항목 최대 3개 (ref + why: 왜 중요한지 35자 이내)
- themes: 주제 묶음 최대 5개 (name 12자 이내 + 그 묶음의 항목 refs + insight: 이 묶음에서 보이는 흐름이나 다음 단계 60자 이내). 항목이 하나뿐인 주제도 괜찮다.
- todos: 실제로 해야 할 일 최대 6개 (text 30자 이내, 관련 항목 ref 없으면 빈 문자열, when: 오늘/이번 주/언젠가). 막연한 "확인하기"보다 구체적으로.
- read_later: 나중에 시간 내서 볼 항목 refs (영상·긴 글)
- lock: 잠금화면 카드 — title(16자 이내, 큰 글씨) + lines(최대 3줄, 각 20자 이내, 중요한 것부터, 명사형)
- tomorrow: 내일 아침 다시 볼 한 가지 (40자 이내)

규칙: 분석 결과에 있는 사실만 쓴다. 숫자·고유명사는 그대로. 간결한 평서문·명사형, 이모지 금지.

항목 분석 결과:
{items}
"""

# ---------- 규칙 기반 (AI 못 쓸 때) ----------
KEYWORDS = {
    "부동산": "아파트 부동산 매매 전세 월세 청약 분양 재건축 재개발 입주 매물 실거래 호갱노노 임장 등기 취득세 양도세 DSR LTV 신도시 단지 세대 평형 ㎡ 주담대 정비사업",
    "재테크·투자": "주식 ETF 코인 비트코인 배당 금리 환율 투자 증권 나스닥 QQQ TQQQ 토스증권 연금 ISA 펀드 채권 수익률 매수 매도",
    "AI·테크": "AI GPT Claude 클로드 코덱스 Codex 챗GPT ChatGPT LLM 자동화 개발 깃허브 GitHub 앱 코딩 프롬프트 에이전트 Anthropic OpenAI 오픈AI 모델 API",
    "업무": "회의 보고 교육 결재 농협 업무 엑셀 기획 제안서 회의록 출장 보고서 PPT 교안",
    "콘텐츠·SNS": "유튜브 인스타 릴스 쇼츠 블로그 채널 조회수 썸네일 편집 구독자 스레드 틱톡 콘텐츠",
    "쇼핑": "쿠팡 구매 할인 최저가 상품 배송 스토어 장바구니 특가 쇼핑 리뷰 가격",
    "건강·운동": "운동 헬스 다이어트 병원 건강 스쿼트 러닝 식단 수면 영양제 PT",
    "맛집·여행": "맛집 카페 여행 호텔 숙소 항공 메뉴 식당 예약 관광 캠핑",
    "생활·정보": "정책 지원금 신청 생활 꿀팁 날씨 행정 세금 보험 할인쿠폰 공지",
}
TODO_HINT = re.compile(r"(하기|챙기기|사기|신청|예약|확인|전화|보내기|제출|마감|까지|해야|할 것|todo|TODO)")
SITE_CAT = {"realestate": "부동산", "shopping": "쇼핑", "code": "AI·테크", "sns": "콘텐츠·SNS"}


def heuristic_item(it: dict, categories: list[str]) -> dict:
    meta = it.get("meta") or {}
    blob = " ".join(str(x) for x in (it.get("text"), meta.get("title"), meta.get("description"), meta.get("channel")) if x)
    cat = SITE_CAT.get(meta.get("site_kind", ""), "")
    if not cat:
        best = max(KEYWORDS, key=lambda c: sum(1 for w in KEYWORDS[c].split() if w.lower() in blob.lower()))
        cat = best if any(w.lower() in blob.lower() for w in KEYWORDS[best].split()) else "기타"
    if cat not in categories:
        cat = "기타" if "기타" in categories else categories[-1]
    kind = it["kind"]
    first_line = (it.get("text") or "").strip().split("\n")[0]
    title = (meta.get("title") or first_line or KIND_KO.get(kind, kind)).strip()
    title = re.sub(r"https?://\S+", "", title).strip() or (meta.get("site") or "링크")
    summary = meta.get("description") or (it.get("text") or "")[:160]
    intent = {"link": "나중에 읽기", "image": "참고 자료", "video": "기록", "file": "참고 자료",
              "audio": "기록"}.get(kind, "기록")
    if kind == "text" and TODO_HINT.search(it.get("text") or ""):
        intent = "할 일"
    if meta.get("site_kind") == "shopping":
        intent = "구매 검토"
    if meta.get("placeholder"):
        summary = f"{KIND_KO.get(kind, kind)} (원본이 없어 내용 확인 불가)"
    return {"category": cat, "title": title[:28], "summary": summary[:300], "key_points": [],
            "intent": intent, "actions": [first_line[:25]] if intent == "할 일" else [], "tags": [],
            "importance": 3 if intent == "할 일" else (1 if meta.get("placeholder") else 2),
            "lock_line": title[:18], "source": "heuristic"}


# ---------- AI 분석 ----------
def _describe(ref: str, it: dict, img_no: int | None) -> str:
    meta = it.get("meta") or {}
    t = parse_iso(it["ts"]).strftime("%H:%M")
    lines = [f"[{ref}] 종류={KIND_KO.get(it['kind'], it['kind'])} 보낸시각={t} 출처={'카톡' if it['source'] == 'kakao' else '폰 공유'}"]
    text = (it.get("text") or "").strip()
    if text:
        lines.append("    메시지: " + text[:700].replace("\n", " ⏎ "))
    if it["kind"] == "link":
        lines.append("    링크: " + (it.get("url") or ""))
        lines.append("    링크정보: " + summarize_meta_for_prompt(meta))
    if img_no is not None:
        lines.append(f"    첨부 이미지 #{img_no} 가 이 항목의 캡처다")
    if meta.get("pdf_text"):
        lines.append("    파일 본문(일부): " + meta["pdf_text"][:2000].replace("\n", " "))
    if meta.get("placeholder"):
        lines.append("    (원본 파일 없음 — 자리표시만 있음)")
    return "\n".join(lines)


def analyze_batch(items: list[dict], settings: dict) -> dict[str, dict]:
    """항목 묶음을 AI 로 분석. 결과: item id → 분석 dict."""
    cats = settings["categories"]
    refs: dict[str, dict] = {}
    blocks, images = [], []
    with tempfile.TemporaryDirectory(prefix="haru-img-") as td:
        for i, it in enumerate(items, 1):
            ref = f"A{i}"
            refs[ref] = it
            img_no = None
            if it["kind"] == "image" and it.get("media"):
                src = config.MEDIA / it["media"]
                if src.exists():
                    try:
                        p = Path(td) / f"img{len(images) + 1}.jpg"
                        p.write_bytes(bytes_to_jpeg(src.read_bytes()))
                        images.append(p)
                        img_no = len(images)
                    except Exception:
                        pass
            blocks.append(_describe(ref, it, img_no))
        prompt = ITEM_PROMPT.format(profile=settings.get("profile", ""), intents=" / ".join(INTENTS),
                                    categories=", ".join(cats), items="\n".join(blocks))
        data = run_json(prompt, item_schema(cats), images, settings)
    out: dict[str, dict] = {}
    llm_info = data.get("_llm", {})
    for row in data.get("items", []):
        it = refs.get(str(row.get("ref", "")).strip())
        if not it:
            continue
        row = {k: v for k, v in row.items() if k != "ref"}
        row["importance"] = max(1, min(5, int(row.get("importance") or 2)))
        row["source"] = llm_info.get("backend", "ai")
        out[it["id"]] = row
    return out


def analyze_items(items: list[dict], settings: dict, log=print) -> dict:
    """status=enriched 항목들을 분석해 저장. 같은 링크를 전에 분석했으면 재사용."""
    cats = settings["categories"]
    todo: list[dict] = []
    stats = Counter()
    for it in items:
        meta = it.get("meta") or {}
        if meta.get("placeholder") or it["kind"] in ("video", "audio"):   # 영상·음성은 AI 가 못 봄
            store.update_item(it["id"], analysis=heuristic_item(it, cats), status="analyzed")
            stats["placeholder"] += 1
            continue
        if it.get("url_key"):
            prev = store.find_analyzed_by_url(it["url_key"], it["id"])
            if prev and prev.get("analysis"):
                a = dict(prev["analysis"], reused_from=prev["id"])
                store.update_item(it["id"], analysis=a, status="analyzed")
                stats["reused"] += 1
                continue
        todo.append(it)
    backend = settings["llm"].get("backend", "codex")
    batch = max(1, int(settings["llm"].get("batch", 5)))
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        result: dict[str, dict] = {}
        if backend != "fake":
            try:
                result = analyze_batch(chunk, settings)
                stats["ai"] += len(result)
            except LLMError as e:
                log(f"AI 분석 실패 → 규칙 기반으로 대신: {e}")
                store.log_event("error", f"AI 분석 실패: {str(e)[:200]}")
        for it in chunk:
            a = result.get(it["id"])
            if a is None:
                a = heuristic_item(it, cats)
                stats["heuristic"] += 1
            store.update_item(it["id"], analysis=a, status="analyzed")
        log(f"  분석 {min(i + batch, len(todo))}/{len(todo)}")
    return dict(stats)


# ---------- 하루 보고서 ----------
def item_sig(items: list[dict]) -> str:
    h = hashlib.sha1()
    for it in items:
        h.update(f"{it['id']}|{it['status']}|{json.dumps(it.get('analysis'), sort_keys=True, ensure_ascii=False)}".encode())
    return h.hexdigest()[:16]


def day_stats(items: list[dict]) -> dict:
    cats, kinds, hours, src = Counter(), Counter(), Counter(), Counter()
    for it in items:
        a = it.get("analysis") or {}
        cats[a.get("category", "기타")] += 1
        kinds[it["kind"]] += 1
        hours[parse_iso(it["ts"]).hour] += 1
        src[it["source"]] += 1
    peak = max(hours, key=hours.get) if hours else None
    return {"count": len(items), "categories": cats.most_common(), "kinds": dict(kinds),
            "sources": dict(src), "peak_hour": peak,
            "first": items[0]["ts"] if items else None, "last": items[-1]["ts"] if items else None}


def week_trend(day: str) -> dict:
    """최근 7일 vs 그 전 7일 카테고리 건수."""
    def window(end: str) -> Counter:
        c = Counter()
        for k in range(7):
            for it in store.items_for_day(shift_day(end, -k)):
                c[(it.get("analysis") or {}).get("category", "기타")] += 1
        return c
    cur, prev = window(day), window(shift_day(day, -7))
    rows = [{"category": c, "n": n, "prev": prev.get(c, 0)} for c, n in cur.most_common(6)]
    return {"rows": rows, "total": sum(cur.values()), "prev_total": sum(prev.values())}


def _item_view(it: dict) -> dict:
    a = it.get("analysis") or {}
    meta = it.get("meta") or {}
    thumb = None
    if it.get("media") and it["kind"] == "image":
        p = Path(it["media"])
        thumb = str(p.with_name(p.stem + ".thumb.jpg"))
    return {
        "id": it["id"], "ts": it["ts"], "time": parse_iso(it["ts"]).strftime("%H:%M"), "kind": it["kind"],
        "source": it["source"], "url": it.get("url"), "site": meta.get("site"), "site_kind": meta.get("site_kind"),
        "text": (it.get("text") or "")[:500], "media": it.get("media"), "thumb": thumb,
        "link_title": meta.get("title"), "image": meta.get("image"), "duration": meta.get("duration"),
        "channel": meta.get("channel"), "note": meta.get("note") or meta.get("error"),
        "category": a.get("category", "기타"), "title": a.get("title") or meta.get("title") or "",
        "summary": a.get("summary", ""), "key_points": a.get("key_points", []), "intent": a.get("intent", ""),
        "actions": a.get("actions", []), "tags": a.get("tags", []), "importance": a.get("importance", 2),
        "lock_line": a.get("lock_line", ""), "analysis_source": a.get("source", ""),
    }


def heuristic_digest(day: str, views: list[dict]) -> dict:
    cats = Counter(v["category"] for v in views)
    top = sorted(views, key=lambda v: (-v["importance"], v["ts"]))
    main = [c for c, _ in cats.most_common(2)]
    todos = [{"text": a, "ref": v["id"], "when": "이번 주"} for v in top for a in v["actions"]][:6]
    return {
        "headline": (" · ".join(main) + " 위주로 모은 날") if main else "조용한 하루",
        "summary": f"{len(views)}개를 모았다. " + ", ".join(f"{c} {n}개" for c, n in cats.most_common(4)) + ".",
        "highlights": [{"ref": v["id"], "why": v["summary"][:35] or v["title"]} for v in top[:3]],
        "themes": [{"name": c, "refs": [v["id"] for v in views if v["category"] == c],
                    "insight": f"{n}개 모음"} for c, n in cats.most_common(5)],
        "todos": todos,
        "read_later": [v["id"] for v in views if v["intent"] == "나중에 읽기"][:6],
        "lock": {"title": f"오늘 {len(views)}개 모음", "lines": [v["lock_line"] or v["title"][:20] for v in top[:3]]},
        "tomorrow": top[0]["title"] if top else "",
        "_llm": {"backend": "heuristic"},
    }


def build_digest(day: str, settings: dict, force: bool = False, log=print) -> dict | None:
    items = [i for i in store.items_for_day(day) if i["status"] == "analyzed"]
    if not items:
        return None
    sig = item_sig(items)
    cur = store.get_digest(day)
    if cur and cur.get("item_sig") == sig and not force:
        return cur["data"]
    views = [_item_view(i) for i in items]
    ref_of = {v["id"]: f"B{n}" for n, v in enumerate(views, 1)}
    id_of = {r: i for i, r in ref_of.items()}
    data: dict | None = None
    if settings["llm"].get("backend") != "fake":
        lines = []
        for v in views:
            lines.append(json.dumps({"ref": ref_of[v["id"]], "시각": v["time"], "종류": KIND_KO.get(v["kind"]),
                                     "카테고리": v["category"], "제목": v["title"], "요약": v["summary"],
                                     "포인트": v["key_points"], "의도": v["intent"], "할일후보": v["actions"],
                                     "중요도": v["importance"],
                                     "길이": f"{v['duration'] // 60}분" if v.get("duration") else ""},
                                    ensure_ascii=False))
        trend = week_trend(day)
        trend_txt = ", ".join(f"{r['category']} {r['n']}건(전주 {r['prev']})" for r in trend["rows"]) or "기록 없음"
        prompt = DIGEST_PROMPT.format(label=day_label(day), n=len(views), profile=settings.get("profile", ""),
                                      trend=trend_txt, items="\n".join(lines))
        try:
            data = run_json(prompt, DIGEST_SCHEMA, (), settings, effort=settings["llm"].get("digest_effort", "medium"))
        except LLMError as e:
            log(f"보고서 AI 실패 → 규칙 기반: {e}")
            store.log_event("error", f"보고서 AI 실패: {str(e)[:200]}")
    if data is None:
        data = heuristic_digest(day, views)
        conv = lambda r: r  # 규칙 기반은 이미 실제 id
    else:
        conv = lambda r: id_of.get(str(r).strip(), "")
    done = store.todos_done()
    todos = []
    for t in data.get("todos", []):
        key = hashlib.sha1(f"{day}|{t.get('text', '')}".encode()).hexdigest()[:12]
        todos.append({"text": t.get("text", ""), "id": conv(t.get("ref", "")), "when": t.get("when", "이번 주"),
                      "key": key, "done": key in done})
    digest = {
        "day": day, "label": day_label(day), "generated_at": iso(now()),
        "headline": data.get("headline", ""), "summary": data.get("summary", ""),
        "highlights": [{"id": conv(h.get("ref")), "why": h.get("why", "")} for h in data.get("highlights", [])
                       if conv(h.get("ref"))],
        "themes": [{"name": t.get("name", ""), "ids": [x for x in (conv(r) for r in t.get("refs", [])) if x],
                    "insight": t.get("insight", "")} for t in data.get("themes", [])],
        "todos": todos,
        "read_later": [x for x in (conv(r) for r in data.get("read_later", [])) if x],
        "lock": {"title": (data.get("lock") or {}).get("title", ""),
                 "lines": [ln for ln in (data.get("lock") or {}).get("lines", []) if ln][:3]},
        "tomorrow": data.get("tomorrow", ""),
        "stats": day_stats(items), "trend": week_trend(day),
        "items": views, "llm": data.get("_llm", {}),
    }
    ver = store.save_digest(day, digest, sig)
    digest["version"] = ver
    log(f"  보고서 v{ver} ({digest['llm'].get('backend')})")
    return digest
