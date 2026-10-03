"""같은 하루 보고서를 노트북의 날짜별 파일·분류 폴더로 보관한다."""
from __future__ import annotations

import csv
import fcntl
import hashlib
import html
import io
import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlsplit

from . import config, store

MANIFEST = ".haru-files.json"


def root(settings: dict | None = None) -> Path:
    s = settings if settings is not None else config.load_settings()
    custom = s.get("archive", {}).get("directory")
    return Path(custom).expanduser() if custom else config.INBOX / "정리"


def day_dir(day: str, settings: dict | None = None) -> Path:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("날짜 형식은 YYYY-MM-DD예요")
    date.fromisoformat(day)
    base = root(settings).resolve()
    folder = base / day
    if not folder.resolve().is_relative_to(base):
        raise ValueError("보고서 폴더가 보관 경로를 벗어났어요")
    return folder


def _name(value: str) -> str:
    label = re.sub(r"[^\w가-힣· -]", "_", str(value)).strip(" ._")[:40] or "항목"
    return f"{label}-{hashlib.sha256(str(value).encode()).hexdigest()[:8]}"


def _url(value: str | None) -> str:
    value = str(value or "").strip()
    if any(ord(c) < 32 for c in value):
        return ""
    try:
        parts = urlsplit(value)
        return value if parts.scheme.lower() in ("http", "https") and parts.netloc else ""
    except ValueError:
        return ""


def _md(value) -> str:
    text = html.escape(str(value or ""), quote=False)
    return re.sub(r"([\\`*_\[\]])", r"\\\1", text)


def _link(label, url) -> str:
    safe = _url(url)
    return f"[{_md(label)}](<{safe.replace('<', '%3C').replace('>', '%3E')}>)" if safe else _md(label)


def _csv_cell(value) -> str:
    text = str(value or "")
    # 메시지나 AI 제목을 엑셀 수식으로 실행하지 않도록 문자열로 보관.
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")) else text


def _digest_md(digest: dict, item_files: dict[str, str]) -> str:
    lines = [f"# {_md(digest.get('headline') or digest['day'])}", "",
             f"{digest.get('label', digest['day'])} · 보고서 v{digest['version']}", "",
             _md(digest.get("summary")), "", "## 핵심 내용", ""]
    items = {i["id"]: i for i in digest.get("items", [])}
    for row in digest.get("highlights", []):
        item = items.get(row.get("id"), {})
        lines.append(f"- **{_md(item.get('title'))}** — {_md(row.get('why'))}")
    lines += ["", "## 할 일", ""]
    for todo in digest.get("todos", []):
        lines.append(f"- [{'x' if todo.get('done') else ' '}] {_md(todo.get('text'))} ({_md(todo.get('when'))})")
    if not digest.get("todos"):
        lines.append("추출된 할 일이 없습니다.")
    lines += ["", "## 나중에 볼 것", ""]
    for ident in digest.get("read_later", []):
        item = items.get(ident)
        if item:
            lines.append(f"- [{_md(item.get('title'))}](<{item_files[ident]}>)")
    lines += ["", "## 주제별 정리", ""]
    for theme in digest.get("themes", []):
        lines += [f"### {_md(theme.get('name'))}", "", _md(theme.get("insight")), ""]
    lines += ["## 모은 자료", ""]
    for item in digest.get("items", []):
        lines.append(f"- [{_md(item.get('title'))}](<{item_files[item['id']]}>) · {_md(item.get('category'))}")
    if not items:
        lines.append("보고서에 남은 항목이 없습니다.")
    lines += ["", "## 다음에 할 것", "", _md(digest.get("tomorrow")), ""]
    return "\n".join(lines)


def _report_html(digest: dict, assets: dict[str, str]) -> str:
    esc = lambda v: html.escape(str(v or ""), quote=True)
    items = {i["id"]: i for i in digest.get("items", [])}
    highlights = "".join(f"<li><strong>{esc(items.get(h.get('id'), {}).get('title'))}</strong><p>{esc(h.get('why'))}</p></li>"
                         for h in digest.get("highlights", []))
    todos = "".join(f"<li>{'☑' if t.get('done') else '☐'} {esc(t.get('text'))}<small>{esc(t.get('when'))}</small></li>"
                    for t in digest.get("todos", [])) or "<li>추출된 할 일이 없습니다.</li>"
    themes = "".join(f"<div><h3>{esc(t.get('name'))}</h3><p>{esc(t.get('insight'))}</p></div>"
                     for t in digest.get("themes", []))
    later = []
    for ident in digest.get("read_later", []):
        item = items.get(ident)
        if item:
            safe = _url(item.get("url"))
            title = esc(item.get("title"))
            later.append(f'<li><a href="{esc(safe)}" target="_blank" rel="noopener noreferrer">{title}</a></li>'
                         if safe else f"<li>{title}</li>")
    read_later = f'<section><h2>나중에 볼 것</h2><ul>{"".join(later)}</ul></section>' if later else ""
    cards = []
    for item in items.values():
        href = _url(item.get("url"))
        link = f'<a href="{esc(href)}" target="_blank" rel="noopener noreferrer">원문 열기 ↗</a>' if href else ""
        asset = assets.get(item["id"])
        media = ""
        if asset:
            src = quote(asset)
            media = (f'<a href="{src}"><img src="{src}" alt="{esc(item.get("title"))}" loading="lazy"></a>'
                     if item.get("kind") == "image" else f'<a href="{src}">첨부 파일 열기</a>')
        points = "".join(f"<li>{esc(p)}</li>" for p in item.get("key_points", []))
        note = f'<p class="meta">{esc(item["note"])}</p>' if item.get("note") else ""
        cards.append(f'<article><span class="tag">{esc(item.get("category"))}</span><h3>{esc(item.get("title"))}</h3>'
                     f'<p>{esc(item.get("summary"))}</p><ul>{points}</ul>{media}{note}{link}</article>')
    content = "".join(cards) or "<p>보고서에 남은 항목이 없습니다.</p>"
    backend = "AI 분석" if digest.get("llm", {}).get("backend") not in (None, "heuristic", "fake") else "규칙 기반 정리"
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'self' file:; base-uri 'none'; form-action 'none'">
<title>{esc(digest['day'])} · 하루서랍 보고서</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f4f0;color:#262925;font-family:system-ui,-apple-system,sans-serif;line-height:1.7}}
main{{max-width:920px;margin:auto;padding:40px 24px 80px}}header{{border-bottom:1px solid #d7ddd4;padding-bottom:30px;margin-bottom:30px}}
.brand{{font-size:14px;font-weight:750;letter-spacing:2px;color:#45644b}}h1{{font-size:clamp(28px,5vw,42px);line-height:1.3;letter-spacing:-1px;margin:18px 0}}
h2{{font-size:23px;margin:0 0 16px}}h3{{font-size:19px;margin:12px 0 8px}}p{{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0 16px}}
.meta,small{{color:#647061;font-size:13px}}small{{display:block;margin-left:24px}}section{{margin:30px 0}}ul{{padding-left:24px}}
.checklist{{list-style:none;padding:0}}.checklist li{{padding:10px 0;border-bottom:1px solid #e0e5dc}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}
article{{border:1px solid #dce2d7;border-radius:16px;background:#fff;padding:24px;min-width:0}}a{{color:#356740;overflow-wrap:anywhere;text-underline-offset:4px}}
.tag{{font-size:12px;padding:5px 10px;border-radius:20px;background:#edf3e8;color:#406348}}img{{max-width:100%;max-height:340px;object-fit:contain;border-radius:8px}}
nav{{display:flex;flex-wrap:wrap;gap:16px;margin-top:20px;font-size:14px}}footer{{margin-top:40px;border-top:1px solid #d7ddd4;padding-top:16px}}
@media(max-width:600px){{main{{padding:28px 18px 60px}}.grid{{grid-template-columns:1fr}}article{{padding:20px}}}}
@media print{{body{{background:white}}main{{padding:0}}article{{break-inside:avoid}}nav{{display:none}}}}
</style></head><body><main><header><div class="brand">하루서랍 · DAILY REPORT</div>
<p class="meta">{esc(digest.get('label', digest['day']))} · {len(items)}개 자료 · 보고서 v{digest['version']} · {backend}</p>
<h1>{esc(digest.get('headline'))}</h1><p>{esc(digest.get('summary'))}</p>
<nav><a href="보고서.md">보고서 Markdown</a><a href="할일.md">할 일</a><a href="링크.csv">링크 목록</a></nav></header>
<section><h2>핵심 내용</h2><ul>{highlights}</ul></section>
<section><h2>할 일</h2><ul class="checklist">{todos}</ul></section>
{read_later}
<section><h2>주제별 정리</h2>{themes}</section>
<section><h2>모은 자료</h2><div class="grid">{content}</div></section>
<section><h2>다음에 할 것</h2><p>{esc(digest.get('tomorrow'))}</p></section>
<footer class="meta">정리 시각 {esc(digest.get('generated_at'))} · 같은 보고서를 노트북과 폰에서 봅니다.</footer>
</main></body></html>'''


def _destination(folder: Path, relative: str) -> Path:
    path = folder / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(folder.resolve()):
        raise ValueError("파일 경로가 보고서 폴더를 벗어났어요")
    return path


def _write(path: Path, content: bytes) -> None:
    if path.is_file() and path.read_bytes() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".haru-", delete=False) as stream:
        tmp = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)


def export_day(day: str, settings: dict | None = None) -> Path | None:
    s = settings if settings is not None else config.load_settings()
    if not s.get("archive", {}).get("enabled", True):
        return None
    folder = day_dir(day, s)
    folder.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder.parent / ".archive.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        row = store.get_digest(day)
        if not row:
            return None
        digest = row["data"]
        digest["version"] = row["version"]
        done = store.todos_done()
        for todo in digest.get("todos", []):
            todo["done"] = todo.get("key") in done
        files: dict[str, bytes] = {}
        item_files, assets = {}, {}
        for item in digest.get("items", []):
            item_id = item["id"]
            ident = hashlib.sha256(item_id.encode()).hexdigest()[:16]
            relative = f"분류/{_name(item.get('category') or '기타')}/{_name(item.get('title') or '항목')}-{ident}.md"
            item_files[item_id] = relative
            raw = store.get_item(item_id) or {}
            media = item.get("media")
            if media:
                original = (config.MEDIA / media).resolve()
                if original.is_relative_to(config.MEDIA.resolve()) and original.is_file():
                    suffix = original.suffix.lower()
                    asset = f"원본/{ident}{suffix}" if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else f"원본/{ident}.bin"
                    files[asset] = original.read_bytes()
                    assets[item_id] = asset
            lines = [f"# {_md(item.get('title'))}", "", f"{_md(item.get('category'))} · {_md(item.get('time'))}", "",
                     "## 분석", "", _md(item.get("summary")), ""]
            lines += [f"- {_md(p)}" for p in item.get("key_points", [])]
            lines += ["", f"보관 의도: {_md(item.get('intent'))}", "", "## 할 일 후보", ""]
            lines += [f"- {_md(action)}" for action in item.get("actions", [])]
            lines += ["", "## 원문", "", _md(raw.get("text") or item.get("text")), ""]
            if item.get("url"):
                lines += [_link("원문 링크", item["url"]), ""]
            if item_id in assets:
                lines += [f"[첨부 원본](<../../{assets[item_id]}>)", ""]
            if item.get("note"):
                lines += [_md(item["note"]), ""]
            files[relative] = "\n".join(lines).encode()
        report = _digest_md(digest, item_files)
        files["보고서.md"] = report.encode()
        files["보고서.html"] = _report_html(digest, assets).encode()
        files["할일.md"] = ("# 할 일\n\n" + "\n".join(
            f"- [{'x' if t.get('done') else ' '}] {_md(t.get('text'))} ({_md(t.get('when'))})" for t in digest.get("todos", [])) + "\n").encode()
        files["보고서.json"] = json.dumps(digest, ensure_ascii=False, indent=2).encode()
        csv_text = io.StringIO(newline="")
        writer = csv.writer(csv_text)
        writer.writerow(["시각", "분류", "제목", "요약", "URL"])
        for item in digest.get("items", []):
            if _url(item.get("url")):
                writer.writerow([_csv_cell(item.get(k)) for k in ("time", "category", "title", "summary", "url")])
        files["링크.csv"] = csv_text.getvalue().encode("utf-8-sig")
        folder.mkdir(exist_ok=True, mode=0o700)
        manifest_path = _destination(folder, MANIFEST)
        try:
            previous = json.loads(manifest_path.read_text()).get("files", {})
        except (OSError, ValueError, AttributeError):
            previous = {}
        for relative, content in files.items():
            _write(_destination(folder, relative), content)
        # 이전에 우리가 만든 파일만 정리한다. 별도 메모·사용자가 수정한 오래된 파일은 보존.
        for relative, checksum in previous.items():
            if relative not in files:
                path = _destination(folder, relative)
                if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == checksum:
                    path.unlink()
                    parent = path.parent
                    while parent != folder:
                        try:
                            parent.rmdir()
                        except OSError:
                            break
                        parent = parent.parent
        manifest = {"day": day, "version": digest["version"], "files": {
            name: hashlib.sha256(content).hexdigest() for name, content in files.items()}}
        _write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode())
        return folder


def refresh_todo(key: str) -> None:
    for day in store.days_for_todo(key):
        try:
            export_day(day)
        except (OSError, ValueError) as exc:
            store.log_event("error", f"할 일 파일 갱신 실패: {str(exc)[:160]}")
