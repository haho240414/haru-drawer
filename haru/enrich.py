"""링크 내용 가져오기: 제목·설명·본문 일부·영상 정보. 실패해도 메시지에 붙은 글로 분석은 계속한다."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

import requests
from bs4 import BeautifulSoup

from .links import host_of, site_kind

UA_MOBILE = ("Mozilla/5.0 (Linux; Android 15; SM-S921N) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/140.0.0.0 Mobile Safari/537.36")
UA_DESKTOP = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/140.0.0.0 Safari/537.36")
# 카톡이 링크 미리보기를 만들 때 쓰는 이름 — 인스타·스레드는 이걸로 열어야 카톡에서 보던 미리보기 글이 나온다
UA_PREVIEW = "kakaotalk-scrap/1.0 (+https://devtalk.kakao.com/)"
TEXT_LIMIT = 3500
TIMEOUT = 15


def _session(mobile: bool = True, ua: str | None = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": ua or (UA_MOBILE if mobile else UA_DESKTOP),
                      "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6"})
    return s


def _clean(t: str | None, limit: int = TEXT_LIMIT) -> str:
    t = re.sub(r"[ \t ]+", " ", t or "")
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    return t[:limit]


def _meta(soup: BeautifulSoup) -> dict:
    def pick(*names):
        for n in names:
            tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return ""
    title = pick("og:title", "twitter:title") or (soup.title.string.strip() if soup.title and soup.title.string else "")
    return {
        "title": title[:200],
        "description": pick("og:description", "description", "twitter:description")[:600],
        "image": pick("og:image", "twitter:image"),
        "site_name": pick("og:site_name"),
        "published": pick("article:published_time", "og:regDate", "datePublished"),
    }


def _article_text(html: str, url: str) -> str:
    try:
        import trafilatura
        txt = trafilatura.extract(html, url=url, include_comments=False, include_tables=True, favor_recall=True)
        return _clean(txt)
    except Exception:
        return ""


def fetch_generic(url: str, mobile: bool = True, ua: str | None = None) -> dict:
    s = _session(mobile, ua)
    r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
    out = {"final_url": r.url, "status": r.status_code}
    ctype = r.headers.get("content-type", "")
    if "pdf" in ctype:
        out.update(title=url.rsplit("/", 1)[-1], content_type="pdf")
        return out
    if "html" not in ctype and "xml" not in ctype:
        out["content_type"] = ctype.split(";")[0]
        return out
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    html = r.text
    soup = BeautifulSoup(html, "lxml")
    out.update(_meta(soup))
    out["text"] = _article_text(html, r.url)
    if r.status_code >= 400:
        # 오류 페이지 글('Access Denied' 등)을 내용으로 착각하지 않게 버린다
        out = {"final_url": r.url, "status": r.status_code, "error": f"HTTP {r.status_code}"}
    return out


def fetch_naver_blog(url: str) -> dict:
    """blog.naver.com 은 본문이 iframe 안 → 모바일 주소(m.blog.naver.com/아이디/글번호)로 본문을 읽는다."""
    sp = urlsplit(url)
    qs = parse_qs(sp.query)
    parts = [p for p in sp.path.split("/") if p]
    blog_id = (qs.get("blogId") or [None])[0]
    log_no = (qs.get("logNo") or [None])[0]
    if not blog_id and len(parts) >= 2 and parts[1].isdigit():
        blog_id, log_no = parts[0], parts[1]
    target = f"https://m.blog.naver.com/{blog_id}/{log_no}" if blog_id and log_no else url
    s = _session(True)
    r = s.get(target, timeout=TIMEOUT)
    soup = BeautifulSoup(r.text, "lxml")
    out = {"final_url": r.url, "status": r.status_code, **_meta(soup)}
    body = soup.select_one(".se-main-container") or soup.select_one("#viewTypeSelector") or soup.select_one(".post_ct")
    out["text"] = _clean(body.get_text("\n") if body else _article_text(r.text, r.url))
    if r.status_code >= 400:
        out["error"] = f"HTTP {r.status_code}"
    return out


def fetch_youtube(url: str) -> dict:
    """제목·채널·길이·설명 + (있으면) 자동 자막 앞부분. yt-dlp 로 메타데이터만 (영상은 안 받음)."""
    out: dict = {}
    try:
        import yt_dlp
        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
                "socket_timeout": TIMEOUT, "extractor_retries": 1}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        out = {
            "final_url": info.get("webpage_url") or url,
            "title": info.get("title") or "",
            "channel": info.get("channel") or info.get("uploader") or "",
            "duration": info.get("duration"),
            "upload_date": info.get("upload_date"),
            "view_count": info.get("view_count"),
            "description": _clean(info.get("description"), 1500),
            "chapters": [c.get("title") for c in (info.get("chapters") or [])][:15],
            "image": info.get("thumbnail") or "",
        }
        subs = (info.get("subtitles") or {}) | (info.get("automatic_captions") or {})
        lang = next((k for k in ("ko", "ko-KR", "en", "en-US") if k in subs), None)
        if lang:
            fmt = next((f for f in subs[lang] if f.get("ext") == "json3"), None)
            if fmt:
                r = requests.get(fmt["url"], timeout=TIMEOUT)
                if r.ok:
                    ev = r.json().get("events", [])
                    words = "".join(seg.get("utf8", "") for e in ev for seg in (e.get("segs") or []))
                    out["transcript"] = _clean(words.replace("\n", " "), 3000)
                    out["transcript_lang"] = lang
    except Exception as e:  # 막히면 oEmbed 로 제목만이라도
        out["error"] = f"yt-dlp: {str(e)[:120]}"
        try:
            r = requests.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"}, timeout=TIMEOUT)
            if r.ok:
                j = r.json()
                out.update(title=j.get("title", ""), channel=j.get("author_name", ""),
                           image=j.get("thumbnail_url", ""))
        except Exception:
            pass
    if out.get("transcript"):
        out["content_basis"] = "partial_transcript"
        out["note"] = "자막 일부와 제목·설명 기준으로 정리했어요. 전체 영상 요약은 아니에요"
    else:
        out["content_basis"] = "metadata_only"
        out["note"] = "자막을 확보하지 못해 제목·설명 기준으로 정리했어요"
    return out


def enrich_link(url: str) -> dict:
    kind, label = site_kind(url)
    host = host_of(url)
    meta: dict = {"site_kind": kind, "site": label, "host": host}
    try:
        if kind == "video" and ("youtube.com" in host or "youtu.be" in host):
            meta.update(fetch_youtube(url))
        elif host.endswith("blog.naver.com"):
            meta.update(fetch_naver_blog(url))
        else:
            mobile = kind not in ("news",)
            meta.update(fetch_generic(url, mobile=mobile, ua=UA_PREVIEW if kind == "sns" else None))
            # 짧은 주소(naver.me 등)는 열어 본 뒤 실제 사이트 종류로 다시 판정
            final = meta.get("final_url") or url
            if host_of(final) != host:
                k2, l2 = site_kind(final)
                meta.update(site_kind=k2, site=l2, host=host_of(final))
                if host_of(final).endswith("blog.naver.com"):
                    meta.update(fetch_naver_blog(final))
    except requests.RequestException as e:
        meta["error"] = f"열 수 없음: {type(e).__name__}"
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    if meta.get("site_kind") == "sns":
        meta.pop("text", None)   # SNS 는 로그인 화면 글이 섞여서 미리보기(제목·설명)만 쓴다
        meta["note"] = "SNS 게시물은 카톡 미리보기와 같은 글(제목·설명)만 읽어요"
    if meta.get("error") and meta.get("site_kind") == "shopping":
        meta["note"] = "쇼핑몰이 자동 접속을 막아요 — 메시지에 붙은 상품명으로 분석해요"
    return meta


def summarize_meta_for_prompt(meta: dict) -> str:
    """분석 프롬프트에 넣을 링크 정보 (길이 제한)."""
    keep = {k: meta.get(k) for k in ("site", "title", "channel", "duration", "upload_date", "description",
                                     "chapters", "published", "error", "note", "content_basis",
                                     "youtube_playlists", "saved_at") if meta.get(k)}
    body = meta.get("transcript") or meta.get("text") or ""
    if body:
        keep["본문(일부)"] = body[:2500]
    return json.dumps(keep, ensure_ascii=False)
