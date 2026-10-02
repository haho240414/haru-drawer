"""링크 찾기·정리 (메시지에서 URL 뽑기, 추적용 꼬리표 떼기, 사이트 종류 판별)."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

RE_URL = re.compile(r"""(?:https?://|www\.)[^\s<>"'`]+""", re.IGNORECASE)
_TRAIL = ".,;:!?)]}>」』】〉》'\"…"
_PAIRS = {")": "(", "]": "[", "}": "{"}

# 공유할 때 붙는 추적 꼬리표 — 같은 링크를 하나로 보려고 뗀다 (열 때는 원래 주소)
TRACKING = {
    "si", "feature", "pp", "fbclid", "gclid", "igshid", "igsh", "utm_source", "utm_medium",
    "utm_campaign", "utm_term", "utm_content", "utm_id", "ref_src", "ref_url", "s", "t",
    "share_id", "sharer", "from", "spm", "_branch_match_id", "trk", "mibextid",
}
# 위 이름이지만 지우면 안 되는 사이트별 예외 (유튜브 t=시작 시각, 네이버 쇼핑 등은 유지)
KEEP_BY_HOST = {
    "youtube.com": {"t"},
    "youtu.be": {"t"},
}


def find_urls(text: str) -> list[str]:
    out = []
    for m in RE_URL.finditer(text or ""):
        u = m.group(0)
        # 끝에 붙은 문장부호 떼기 (괄호는 짝이 맞으면 남김)
        while u and u[-1] in _TRAIL:
            ch = u[-1]
            if ch in _PAIRS and u.count(_PAIRS[ch]) >= u.count(ch):
                break
            u = u[:-1]
        if u.lower().startswith("www."):
            u = "https://" + u
        if len(u) > 10 and u not in out:
            out.append(u)
    return out


def host_of(url: str) -> str:
    try:
        h = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return h.lower().removeprefix("www.").removeprefix("m.")


def normalize(url: str) -> str:
    """같은 글을 가리키는 링크를 하나로 보기 위한 키."""
    try:
        sp = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = (sp.hostname or "").lower().removeprefix("www.")
    keep = set()
    for h, ks in KEEP_BY_HOST.items():
        if host.endswith(h):
            keep = ks
    q = [(k, v) for k, v in parse_qsl(sp.query, keep_blank_values=True)
         if k.lower() not in TRACKING or k in keep]
    path = sp.path.rstrip("/") or ""
    # 모바일·PC 주소 통일
    if host.startswith("m.") and any(host.endswith(x) for x in ("naver.com", "youtube.com", "daum.net", "coupang.com")):
        host = host[2:]
    if host == "youtu.be":
        vid = path.strip("/")
        host, path = "youtube.com", "/watch"
        q = [("v", vid)] + [(k, v) for k, v in q if k == "t"]
    if host == "youtube.com" and path.startswith("/shorts/"):
        q = [("v", path.split("/")[2])]
        path = "/watch"
    return urlunsplit(("https", host, path, urlencode(sorted(q)), ""))


SITE_KINDS = [
    (("youtube.com", "youtu.be"), "video", "유튜브"),
    (("blog.naver.com",), "blog", "네이버 블로그"),
    (("cafe.naver.com",), "community", "네이버 카페"),
    (("n.news.naver.com", "news.naver.com", "news.daum.net", "v.daum.net"), "news", "뉴스"),
    (("new.land.naver.com", "land.naver.com", "fin.land.naver.com", "hogangnono.com", "kbland.kr",
      "zigbang.com", "dabangapp.com", "rtms.molit.go.kr", "applyhome.co.kr"), "realestate", "부동산 정보"),
    (("instagram.com",), "sns", "인스타그램"),
    (("threads.net", "threads.com"), "sns", "스레드"),
    (("x.com", "twitter.com"), "sns", "X(트위터)"),
    (("tiktok.com",), "sns", "틱톡"),
    (("facebook.com", "fb.watch"), "sns", "페이스북"),
    (("coupang.com", "link.coupang.com", "smartstore.naver.com", "brand.naver.com", "shopping.naver.com",
      "11st.co.kr", "gmarket.co.kr", "musinsa.com", "ohou.se", "kurly.com", "aliexpress.com", "temu.com"), "shopping", "쇼핑"),
    (("map.naver.com", "naver.me", "place.map.kakao.com", "map.kakao.com", "kko.to"), "map", "지도·장소"),
    (("github.com",), "code", "깃허브"),
    (("docs.google.com", "drive.google.com", "notion.so", "notion.site"), "doc", "문서"),
    (("tistory.com", "brunch.co.kr", "velog.io", "medium.com", "substack.com"), "blog", "블로그"),
]


def site_kind(url: str) -> tuple[str, str]:
    h = host_of(url)
    for hosts, kind, label in SITE_KINDS:
        if any(h == x or h.endswith("." + x) for x in hosts):
            return kind, label
    return "web", h or "웹"
