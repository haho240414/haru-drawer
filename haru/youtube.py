"""읽기 전용 YouTube 재생목록 연결·새 저장분 수집. 기본 Watch Later는 API 미지원."""
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import secrets
import tempfile
import time
from contextlib import contextmanager
from datetime import date, timedelta
from urllib.parse import urlencode, urlsplit, parse_qs
from zoneinfo import ZoneInfo

import requests

from . import config, store
from .timeutil import day_of, iso, now, parse_iso

SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_URL = "https://www.googleapis.com/youtube/v3/"
TOPICS = {"경제": "재테크·투자", "AI": "AI·테크", "휴식": "휴식", "기타": "기타"}


class YouTubeError(RuntimeError):
    pass


@contextmanager
def _lock():
    config.ensure_dirs()
    with (config.DATA / "youtube.lock").open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _auth_path():
    return config.DATA / "youtube-auth.json"


def _read_auth() -> dict:
    try:
        return json.loads(_auth_path().read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _write_auth(data: dict):
    # 계정 토큰은 설정·보고서·Git에 넣지 않고 사용자 전용 파일로 원자 저장.
    config.ensure_dirs()
    fd, name = tempfile.mkstemp(prefix=".youtube-", dir=config.DATA)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(name, _auth_path())
    finally:
        if os.path.exists(name):
            os.unlink(name)


def configure_client(document: dict):
    client = document.get("installed", {})
    if not isinstance(client, dict) or not str(client.get("client_id", "")).endswith(".apps.googleusercontent.com") \
            or not client.get("client_secret"):
        raise YouTubeError("Google의 데스크톱 앱용 OAuth JSON 파일이 필요해요")
    with _lock():
        old = _read_auth()
        picked = {k: str(client[k]) for k in ("client_id", "client_secret")}
        if old.get("client") != picked:
            old = {"client": picked}  # 다른 앱 자격 증명에 이전 토큰을 섞지 않음
        _write_auth(old)


def begin_auth(port: int) -> str:
    with _lock():
        auth = _read_auth()
        if not auth.get("client"):
            raise YouTubeError("먼저 데스크톱 앱용 OAuth JSON 파일을 등록해 주세요")
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        pending = {"state": secrets.token_urlsafe(32), "verifier": verifier, "at": time.time(),
                   "redirect": f"http://127.0.0.1:{int(port)}/api/youtube/oauth/callback"}
        auth["pending"] = pending
        _write_auth(auth)
        return AUTH_URL + "?" + urlencode({
            "client_id": auth["client"]["client_id"], "redirect_uri": pending["redirect"],
            "response_type": "code", "scope": SCOPE, "access_type": "offline", "prompt": "consent",
            "state": pending["state"], "code_challenge": challenge, "code_challenge_method": "S256",
        })


def _token_request(params: dict) -> dict:
    try:
        r = requests.post(TOKEN_URL, data=params, timeout=20)
        data = r.json()
    except (requests.RequestException, ValueError):
        raise YouTubeError("Google 연결을 확인하지 못했어요. 잠시 후 다시 시도해 주세요") from None
    if not r.ok or not isinstance(data, dict) or not data.get("access_token"):
        raise YouTubeError("Google 연결이 만료되었거나 거절됐어요. 계정을 다시 연결해 주세요")
    scopes = set(str(data.get("scope", SCOPE)).split())
    if scopes != {SCOPE}:
        raise YouTubeError("YouTube 읽기 전용 권한으로 다시 연결해 주세요")
    return data


def finish_auth(state: str, code: str, denied: bool = False):
    with _lock():
        auth = _read_auth()
        pending = auth.get("pending") or {}
        if not state or not secrets.compare_digest(state, pending.get("state", "")) \
                or time.time() - pending.get("at", 0) > 600:
            raise YouTubeError("연결 요청이 만료되었어요. 다시 연결을 시작해 주세요")
        auth.pop("pending", None)
        _write_auth(auth)  # 일회용 state, 취소나 실패도 재사용 불가
        if denied or not code:
            raise YouTubeError("Google 계정 연결을 취소했어요")
        token = _token_request({**auth["client"], "code": code, "code_verifier": pending["verifier"],
                                "redirect_uri": pending["redirect"], "grant_type": "authorization_code"})
        if not token.get("refresh_token"):
            raise YouTubeError("자동 수집에 필요한 연결을 받지 못했어요. 다시 연결해 주세요")
        auth["token"] = {"access_token": token["access_token"], "refresh_token": token["refresh_token"],
                         "expires_at": time.time() + int(token.get("expires_in", 3600))}
        _write_auth(auth)


def _access_token() -> str:
    with _lock():
        auth = _read_auth()
        token = auth.get("token") or {}
        if not token.get("refresh_token"):
            raise YouTubeError("유튜브 계정을 먼저 연결해 주세요")
        if token.get("access_token") and token.get("expires_at", 0) > time.time() + 60:
            return token["access_token"]
        fresh = _token_request({**auth["client"], "refresh_token": token["refresh_token"], "grant_type": "refresh_token"})
        auth["token"] = {"access_token": fresh["access_token"], "refresh_token": token["refresh_token"],
                         "expires_at": time.time() + int(fresh.get("expires_in", 3600))}
        _write_auth(auth)
        return fresh["access_token"]


def disconnect():
    with _lock():
        auth = _read_auth()
        _write_auth({"client": auth["client"]} if auth.get("client") else {})
    config.update_settings({"youtube": {"enabled": False, "playlists": []}})


def status(settings: dict | None = None) -> dict:
    auth = _read_auth()
    y = (settings or config.load_settings()).get("youtube", {})
    playlists = y.get("playlists", [])
    if y.get("mode") == "browser":
        playlists = [{**p, "baseline": store.kv_get("youtube_browser_seen:" + p["id"])} for p in playlists]
        playlists = [{**p, "baseline": {k: v for k, v in (p.get("baseline") or {}).items() if k != "ids"}} for p in playlists]
    return {"configured": bool(auth.get("client")), "connected": bool(auth.get("token", {}).get("refresh_token")),
            "mode": y.get("mode", "api"), "browser_schedule": y.get("browser_schedule"),
            "browser_ready": bool(store.kv_get("youtube_browser_ready")),
            "browser_baseline_count": sum((p.get("baseline") or {}).get("visible_count", 0) for p in playlists),
            "enabled": bool(y.get("enabled")), "playlists": playlists,
            "last_sync": store.kv_get("youtube_last_sync"), "watch_later_api_supported": False}


def _pages(resource: str, token: str, **params) -> list[dict]:
    rows, page, seen = [], "", set()
    for _ in range(200):
        try:
            r = requests.get(API_URL + resource, params={**params, "maxResults": 50, "pageToken": page},
                             headers={"Authorization": "Bearer " + token}, timeout=20)
            body = r.json()
        except (requests.RequestException, ValueError):
            raise YouTubeError("유튜브 목록을 가져오지 못했어요. 네트워크를 확인해 주세요") from None
        if not r.ok:
            raise YouTubeError(f"유튜브 목록 조회 실패 (HTTP {r.status_code}). 권한·API 사용 설정·한도를 확인해 주세요")
        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise YouTubeError("유튜브 목록 응답을 확인하지 못했어요")
        rows.extend(body["items"])
        page = body.get("nextPageToken") or ""
        if not page:
            return rows
        if page in seen:
            break
        seen.add(page)
    # 일부 페이지만 받았을 때 성공 처리하거나 기준 목록을 덮어쓰지 않음.
    raise YouTubeError("목록 전체를 가져오지 못했어요. 이번 수집은 다음에 다시 시도해요")


def list_playlists() -> list[dict]:
    rows = _pages("playlists", _access_token(), part="snippet,contentDetails,status", mine="true")
    return [{"id": r["id"], "name": r.get("snippet", {}).get("title", ""),
             "count": r.get("contentDetails", {}).get("itemCount", 0),
             "privacy": r.get("status", {}).get("privacyStatus", "private")} for r in rows]


def playlist_id(value: str) -> str:
    value = str(value).strip()
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.hostname not in ("youtube.com", "www.youtube.com", "m.youtube.com"):
            raise YouTubeError("유튜브 재생목록 주소를 넣어 주세요")
        value = parse_qs(parsed.query).get("list", [""])[0]
    if value in ("WL", "HL"):
        raise YouTubeError("기본 나중에 볼 동영상·시청 기록은 API로 수집할 수 없어요. 직접 만든 재생목록을 선택해 주세요")
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,100}", value):
        raise YouTubeError("재생목록 주소 또는 ID를 확인해 주세요")
    return value


def save_selection(rows: list[dict], enabled: bool) -> dict:
    if not isinstance(rows, list) or len(rows) > 20:
        raise YouTubeError("재생목록은 최대 20개까지 선택할 수 있어요")
    picked, seen = [], set()
    for row in rows:
        pid = playlist_id(row.get("id", ""))
        if pid in seen:
            continue
        topic = row.get("topic", "기타")
        if topic not in TOPICS:
            raise YouTubeError("경제·AI·휴식·기타 중 주제를 선택해 주세요")
        seen.add(pid)
        picked.append({"id": pid, "name": str(row.get("name") or topic)[:100], "topic": topic})
    return config.update_settings({"youtube": {"enabled": bool(enabled and picked), "mode": "api", "playlists": picked}})


def import_browser_snapshot(document: dict, settings: dict | None = None) -> dict:
    """로그인된 화면에서 읽은 전체 목록. 첫 회는 기준만, 다음 회부터 처음 발견한 영상만.

    DOM에는 개별 저장 시각이 없어 captured_at을 발견 시각으로 명시한다.
    목록 끝까지 읽지 못한 자료는 기준을 덮어쓰거나 예전 영상을 새 영상으로 넣지 않는다.
    """
    settings = settings or config.load_settings()
    if not isinstance(document, dict) or document.get("source") != "youtube_browser":
        raise YouTubeError("유튜브 브라우저 수집 파일을 확인해 주세요")
    try:
        captured = parse_iso(document["captured_at"])
    except (KeyError, TypeError, ValueError):
        raise YouTubeError("브라우저 확인 시각이 필요해요") from None
    if abs((now() - captured).total_seconds()) > 3600:
        raise YouTubeError("방금 확인한 목록으로 다시 수집해 주세요")
    selected = settings.get("youtube", {}).get("playlists", [])
    by_id = {p["id"]: p for p in selected}
    rows = document.get("playlists")
    if not isinstance(rows, list) or len(rows) > 20:
        raise YouTubeError("브라우저 재생목록 목록을 확인해 주세요")
    result = {"new": 0, "updated": 0, "baseline": 0, "days": [], "errors": [], "at": iso(captured),
              "collector": "browser", "date_basis": "first_observed_at"}
    with _lock():
        for snapshot in rows:
            pid = snapshot.get("id")
            playlist = by_id.get(pid)
            if not playlist:
                raise YouTubeError("수집 설정에 없는 재생목록이 포함되어 있어요")
            if not snapshot.get("complete") or not isinstance(snapshot.get("videos"), list):
                result["errors"].append({"name": playlist["name"], "message": "전체 목록 확인 실패. 기존 수집 기준을 유지해요"})
                continue
            videos = snapshot["videos"]
            total = snapshot.get("reported_total")
            row_count = snapshot.get("row_count", len(videos))
            if not isinstance(total, int) or total < 0 or row_count != total or row_count < len(videos):
                result["errors"].append({"name": playlist["name"], "message": "화면의 전체 개수와 읽은 개수가 달라 기준을 유지해요"})
                continue
            if len(videos) > 10000 or len({v.get("id") for v in videos}) != len(videos) \
                    or any(not re.fullmatch(r"[A-Za-z0-9_-]{11}", str(v.get("id", ""))) for v in videos):
                raise YouTubeError("브라우저 영상 목록을 확인해 주세요")
            key = "youtube_browser_seen:" + pid
            previous = store.kv_get(key)
            seen = set((previous or {}).get("ids", []))
            # 일부러 첫 연결의 기존 715개 같은 오래된 저장분을 오늘로 보고하지 않음.
            candidates = [] if previous is None else [v for v in videos if v["id"] not in seen]
            day = day_of(captured, settings.get("day_boundary_hour", 4))
            with store.tx():
                for video in candidates:
                    if str(video.get("title", "")).strip() in ("[비공개 동영상]", "[삭제된 동영상]", "[Private video]", "[Deleted video]"):
                        continue
                    vid = video["id"]
                    item_id = f"y:{day}:{vid}"
                    membership = {**playlist, "observed_at": iso(captured)}
                    meta = {"title": str(video.get("title", ""))[:300], "channel": str(video.get("channel", ""))[:200],
                            "site": "유튜브", "site_kind": "video", "youtube_video_id": vid,
                            "youtube_playlists": [membership], "observed_at": iso(captured),
                            "date_basis": "first_observed_at", "note": "개별 저장일을 확인할 수 없어 처음 발견한 날짜에 모았어요"}
                    url = "https://www.youtube.com/watch?v=" + vid
                    old = store.get_item(item_id)
                    if old is None:
                        store.upsert_item({"id": item_id, "day": day, "ts": iso(captured), "source": "youtube",
                                           "kind": "link", "text": "", "url": url, "url_key": url, "meta": meta,
                                           "origin": "youtube_browser:" + str(pid)})
                        result["new"] += 1
                        result["days"].append(day)
                    elif old["status"] != "hidden":
                        existing = dict(old.get("meta") or {})
                        memberships = list(existing.get("youtube_playlists") or [])
                        if not any(m["id"] == pid for m in memberships):
                            existing["youtube_playlists"] = memberships + [membership]
                            store.update_item(item_id, meta=existing, status="enriched", analysis=None)
                            result["updated"] += 1
                            result["days"].append(day)
                store.kv_set(key, {"ids": [v["id"] for v in videos], "at": iso(captured),
                                   "reported_total": total, "visible_count": len(videos)})
            if previous is None:
                result["baseline"] += len(videos)
        result["days"] = sorted(set(result["days"]))
        ready = bool(selected) and all(store.kv_get("youtube_browser_seen:" + p["id"]) is not None for p in selected)
        store.kv_set("youtube_browser_ready", ready)
        store.kv_set("youtube_last_sync", result)
    return result


def browser_due(settings: dict | None = None) -> dict:
    """LA의 두 확인 시각 중 설정된 한국 시각에 하루 한 번만 수집한다."""
    y = (settings or config.load_settings()).get("youtube", {})
    hour = y.get("report_hour", 22)
    if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
        raise YouTubeError("유튜브 보고서 시각은 한국 시간 0~23시 정수여야 해요")
    cur = now().astimezone(ZoneInfo("Asia/Seoul"))
    day = cur.date().isoformat()
    previous = store.kv_get("youtube_browser_daily_run") or {}
    due = y.get("mode") == "browser" and bool(y.get("enabled")) and cur.hour == hour and previous.get("day") != day
    return {"due": due, "day": day, "at": cur.isoformat(timespec="seconds"), "completed_today": previous.get("day") == day}


def browser_done(day: str | None = None) -> dict:
    current = now().astimezone(ZoneInfo("Asia/Seoul")).date()
    day = day if day is not None else current.isoformat()
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or date.fromisoformat(day) > current:
            raise ValueError
    except (TypeError, ValueError):
        raise YouTubeError("완료 날짜는 오늘 또는 이전의 YYYY-MM-DD여야 해요") from None
    previous = store.kv_get("youtube_browser_daily_run") or {}
    if previous.get("day", "") > day:
        raise YouTubeError("더 최근의 완료 기록을 이전 날짜로 바꿀 수 없어요")
    result = {"day": day, "at": iso(now())}
    store.kv_set("youtube_browser_daily_run", result)
    return result


def _import_playlist(playlist: dict, rows: list[dict], settings: dict) -> dict:
    pid = playlist_id(playlist["id"])
    key = "youtube_seen:" + pid
    previous = store.kv_get(key)
    seen = set((previous or {}).get("ids", []))
    cur = now()
    boundary = settings.get("day_boundary_hour", 4)
    today = day_of(cur, boundary)
    # 처음 연결할 때는 오늘 저장분만. 이후 깨어난 뒤 최대 7일의 누락분을 회수.
    earliest = today if previous is None else day_of(cur - timedelta(days=7), boundary)
    prepared, identifiers = [], []
    skipped = 0
    for row in rows:
        snippet = row.get("snippet") or {}
        vid = (row.get("contentDetails") or {}).get("videoId") or snippet.get("resourceId", {}).get("videoId")
        ident = row.get("id")
        if not ident:
            raise YouTubeError("저장 항목 ID가 없는 목록은 다시 조회해야 해요")
        identifiers.append(ident)
        if ident in seen:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", str(vid or "")) \
                or snippet.get("title") in ("Deleted video", "Private video"):
            skipped += 1
            continue
        try:
            ts = parse_iso(snippet["publishedAt"])
        except (KeyError, ValueError, TypeError):
            raise YouTubeError("영상의 저장 시각을 확인하지 못했어요. 이번 목록은 다시 조회해야 해요") from None
        day = day_of(ts, boundary)
        if day < earliest or day > today or ts > cur:
            skipped += 1
            continue
        membership = {"id": pid, "name": playlist["name"], "topic": playlist["topic"], "saved_at": iso(ts)}
        url = "https://www.youtube.com/watch?v=" + vid
        meta = {"title": snippet.get("title", ""), "description": snippet.get("description", "")[:1500],
                "channel": snippet.get("videoOwnerChannelTitle", ""), "site": "유튜브", "site_kind": "video",
                "youtube_video_id": vid, "youtube_playlists": [membership], "saved_at": iso(ts),
                "date_basis": "playlist_added_at"}
        prepared.append({"id": f"y:{day}:{vid}", "day": day, "ts": iso(ts), "source": "youtube", "kind": "link",
                         "text": "", "url": url, "url_key": url, "meta": meta, "origin": "youtube:" + pid})
    added, updated, days = 0, 0, set()
    # 전체 목록 검증 후 항목과 기준을 한 트랜잭션으로 저장.
    with store.tx():
        for item in prepared:
            old = store.get_item(item["id"])
            if old is None:
                store.upsert_item(item)
                added += 1
                days.add(item["day"])
            elif old["status"] != "hidden":
                meta = dict(old.get("meta") or {})
                memberships = list(meta.get("youtube_playlists") or [])
                if not any(m.get("id") == pid for m in memberships):
                    memberships += item["meta"]["youtube_playlists"]
                    meta["youtube_playlists"] = memberships
                    store.update_item(item["id"], meta=meta, status="enriched", analysis=None)
                    updated += 1
                    days.add(item["day"])
        store.kv_set(key, {"ids": list(dict.fromkeys(identifiers)), "at": iso(cur)})
    return {"new": added, "updated": updated, "skipped": skipped, "days": sorted(days)}


def sync(settings: dict | None = None, log=print) -> dict:
    settings = settings or config.load_settings()
    y = settings.get("youtube", {})
    if not y.get("enabled") or not y.get("playlists") or y.get("mode") == "browser":
        return {"new": 0, "updated": 0, "days": [], "errors": []}
    result = {"new": 0, "updated": 0, "skipped": 0, "days": [], "errors": [], "at": iso(now())}
    try:
        token = _access_token()
    except YouTubeError as e:
        result["errors"].append({"name": "계정 연결", "message": str(e)})
        token = None
    if token:
        # 파이프라인과 CLI가 동시에 수집해도 같은 기준으로 처리.
        with _lock():
            for playlist in y["playlists"]:
                try:
                    pid = playlist_id(playlist["id"])
                    rows = _pages("playlistItems", token, part="snippet,contentDetails", playlistId=pid)
                    stats = _import_playlist(playlist, rows, settings)
                    for k in ("new", "updated", "skipped"):
                        result[k] += stats[k]
                    result["days"] = sorted(set(result["days"]) | set(stats["days"]))
                except YouTubeError as e:
                    result["errors"].append({"name": playlist.get("name", "재생목록"), "message": str(e)})
    store.kv_set("youtube_last_sync", result)
    log(f"유튜브 수집: 새 영상 {result['new']}개, 목록 반영 {result['updated']}개, 실패 {len(result['errors'])}개")
    return result
