"""3줄 요약·상세 브리핑·원본 순서의 정리 자료를 일관되게 출력한다."""
from __future__ import annotations

import html
from urllib.parse import quote

from .llm import LLMError
from .reading_style import READING_CSS


def validate_quick(data: dict) -> None:
    lines = data.get("quick_summary")
    if not isinstance(lines, list) or len(lines) != 3 or any(not isinstance(s, str) or not s.strip() for s in lines):
        raise LLMError("3줄 요약이 불완전해요")


def validate_item(data: dict) -> None:
    validate_quick(data)
    sections = data.get("briefing")
    if (not isinstance(sections, list) or not sections
            or any(not isinstance(s, dict) or not all(isinstance(s.get(k), str) and s[k].strip()
                                                     for k in ("heading", "body")) for s in sections)):
        raise LLMError("상세 브리핑이 불완전해요")


def _esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def quick_html(data: dict) -> str:
    lines = data.get("quick_summary") or []
    return '<div class="quick"><h4>3줄 요약</h4><ol>' + ''.join(f'<li>{_esc(s)}</li>' for s in lines) + '</ol></div>' if lines else ''


def briefing_html(item: dict) -> str:
    sections = item.get("briefing") or []
    if not sections:
        return f'<p>{_esc(item.get("summary"))}</p>'
    return ''.join(f'<h4>{_esc(s.get("heading"))}</h4><p>{_esc(s.get("body"))}</p>' for s in sections)


def source_html(item: dict, anchor_prefix: str | None = None) -> str:
    out = []
    chapter = 0
    for group in item.get("transcript_sections", []):
        sections = group.get("sections") or []
        if sections:
            for s in sections:
                chapter += 1
                anchor = f' id="{_esc(anchor_prefix)}-chapter-{chapter}"' if anchor_prefix else ''
                out.append(f'<div class="source-chapter"><h3{anchor}>{_esc(s.get("heading"))}</h3><p class="chapter-time">{_esc(s.get("time"))}</p><p>{_esc(s.get("body"))}</p></div>')
        else:  # 이전 보고서도 계속 읽을 수 있게 한다.
            out.append(f'<h3>구간 {_esc(group.get("part"))}/{_esc(group.get("total"))}</h3><p>{_esc(group.get("summary"))}</p><ul>' +
                       ''.join(f'<li>{_esc(p)}</li>' for p in group.get("points", [])) + '</ul>')
        out.extend(f'<p class="meta">확인 필요: {_esc(s)}</p>' for s in group.get("uncertain", []))
    return ''.join(out)


def quick_md(data: dict, md, level: int = 2) -> list[str]:
    lines = data.get("quick_summary") or []
    return [f"{'#' * level} 3줄 요약", ""] + [f"{n}. {md(s)}" for n, s in enumerate(lines, 1)] + [""] if lines else []


def briefing_md(item: dict, md, level: int = 3) -> list[str]:
    if not item.get("briefing"):
        return [md(item.get("summary")), ""]
    out = []
    for s in item["briefing"]:
        out += [f"{'#' * level} {md(s.get('heading'))}", "", md(s.get("body")), ""]
    return out


def source_md(item: dict, md) -> list[str]:
    out = []
    for group in item.get("transcript_sections", []):
        if group.get("sections"):
            for s in group["sections"]:
                out += [f"### {md(s.get('heading'))}", "", md(s.get("time")), "", md(s.get("body")), ""]
        else:
            out += [f"### 구간 {group.get('part')}/{group.get('total')}", "", md(group.get("summary")), ""]
            out += [f"- {md(p)}" for p in group.get("points", [])] + [""]
        out += [f"- 확인 필요: {md(p)}" for p in group.get("uncertain", [])] + [""]
    return out


SOURCE_NOTICE = "음성·자막을 원본 순서대로 풀어 쓴 정리본입니다. 반복·인사·광고는 축약했습니다. 발언 전문은 TXT·SRT로 대조할 수 있습니다. 제작자의 주장에 대한 사실 검증이나 화면의 표·그래프 확인을 뜻하지 않으며, 음성 인식 오류가 남을 수 있습니다."


def source_document(digest: dict, transcripts: dict[str, str], anchors: dict[str, str], srts: set[str]) -> str:
    items = [i for i in digest.get("items", []) if i.get("transcript_sections")]
    toc = ''.join(f'<li><a href="#{anchors[i["id"]]}">{_esc(i.get("title"))}</a></li>' for i in items)
    body = []
    for item in items:
        anchor = anchors[item["id"]]
        chapters = [s for group in item.get("transcript_sections", []) for s in group.get("sections", [])]
        chapter_toc = ('<details class="chapter-index"><summary>목차 · ' + str(len(chapters)) + '개 이야기</summary><ol>' +
                       ''.join(f'<li><a href="#{anchor}-chapter-{n}"><span>{_esc(s.get("time"))}</span>{_esc(s.get("heading"))}</a></li>'
                               for n, s in enumerate(chapters, 1)) + '</ol></details>') if chapters else ''
        path = transcripts.get(item["id"])
        downloads = f'<a href="{quote(path)}" download>시간 표시 전사 전문 TXT</a>' if path else ''
        if path and item["id"] in srts:
            downloads += f' · <a href="{quote(path[:-4] + ".srt")}" download>시간 표시 자막 SRT</a>'
        body.append(f'<article id="{anchor}"><p class="eyebrow">{_esc(item.get("category"))}</p><h2>{_esc(item.get("title"))}</h2>'
                    f'<p class="meta">{downloads}</p>{chapter_toc}{source_html(item, anchor)}<a class="back-to-contents" href="#contents">영상 목차로 돌아가기</a></article>')
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{_esc(digest['day'])} · 원본 내용 정리</title><style>
{READING_CSS}
</style></head><body><nav class="reading-bar" aria-label="읽기 이동"><a href="보고서.html">← 3줄 요약과 상세 브리핑</a><a href="#contents">영상 목차</a></nav><main><header class="source-intro"><div class="brand">하루서랍</div><p class="eyebrow">조금 더 깊이 읽는 시간</p><h1>원본 내용 정리</h1>
<p class="meta">{_esc(digest.get('label', digest['day']))} · 보고서 v{digest['version']}</p><p class="notice">{SOURCE_NOTICE}</p></header><nav class="contents" id="contents" aria-label="영상 목차"><h2>오늘 모아둔 영상</h2><ol>{toc}</ol></nav>{''.join(body)}</main></body></html>'''
