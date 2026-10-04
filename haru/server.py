"""맥 대시보드 (http://localhost:8891) — 폰 앱과 같은 화면(app/)에 맥 전용 기능(넣기·폰 연결·설정)을 더한 것."""
from __future__ import annotations

import base64
import io
import json
import threading
from urllib.parse import urlsplit
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory, redirect

from . import archive, config, inbox, store, youtube
from .lockcard import card_from_digest, render
from .pipeline import Busy, latest_day, publish_day, run
from .relay import new_pairing, pairing_code
from .timeutil import today

APK_URL = "https://github.com/haho240414/haru-drawer/releases/latest/download/haru-drawer.apk"
app = Flask(__name__, static_folder=None)
_run_thread: threading.Thread | None = None
_run_log: list[str] = []


@app.before_request
def _youtube_local_access():
    if not request.path.startswith("/api/youtube"):
        return
    host = urlsplit(request.host_url)
    if request.remote_addr not in ("127.0.0.1", "::1") or host.hostname not in ("localhost", "127.0.0.1"):
        abort(403)
    if request.method == "POST":
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            abort(403)
        if not request.is_json:
            abort(415)

def _settings() -> dict:
    return config.load_settings()


@app.after_request
def _no_cache(resp):
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    elif not request.path.startswith(("/media/", "/fonts/")):
        # 화면 코드(js·css)는 업데이트 후 바로 반영되게 매번 확인 (안 바뀌었으면 304)
        resp.headers["Cache-Control"] = "no-cache"
    return resp


# ---------- 화면 ----------
@app.get("/")
def index():
    return send_from_directory(config.WEB_DIR, "index.html")


@app.get("/<path:path>")
def static_files(path):
    if path.startswith(("api/", "media/", "cards/")):
        abort(404)
    return send_from_directory(config.WEB_DIR, path)


@app.get("/media/<path:path>")
def media(path):
    return send_from_directory(config.MEDIA, path)


# ---------- 데이터 ----------
@app.get("/api/days")
def api_days():
    s = _settings()
    return jsonify({"days": store.days_with_items(), "today": today(s.get("day_boundary_hour", 4))})


@app.get("/api/day/<day>")
def api_day(day):
    dg = store.get_digest(day)
    items = store.items_for_day(day)
    pending = sum(1 for i in items if i["status"] != "analyzed")
    digest = dg["data"] if dg else None
    if digest:
        done = store.todos_done()
        for t in digest.get("todos", []):
            t["done"] = t.get("key") in done
        digest["version"] = dg["version"]
        digest["published_at"] = dg.get("published_at")
    raw = [{"id": i["id"], "ts": i["ts"], "kind": i["kind"], "text": i.get("text"), "url": i.get("url"),
            "status": i["status"], "source": i["source"], "media": i.get("media")} for i in items]
    try:
        folder = archive.day_dir(day)
        saved = folder / "보고서.html"
        file_archive = {"path": str(folder), "exists": saved.is_file(), "url": f"/reports/{day}/보고서.html"}
    except ValueError:
        file_archive = None
    from . import content
    try:
        draft = content.status(day) if _settings().get("content", {}).get("enabled") else None
    except (OSError, ValueError, KeyError, TypeError):
        draft = None
    return jsonify({"day": day, "digest": digest, "items": raw, "pending": pending, "archive": file_archive,
                    "content_enabled": bool(_settings().get("content", {}).get("enabled")), "content": draft})


@app.post("/api/todo")
def api_todo():
    j = request.get_json(force=True)
    store.set_todo_done(j["key"], bool(j.get("done")))
    from .archive import refresh_todo
    refresh_todo(j["key"])
    return jsonify({"ok": True})


@app.post("/api/item/<path:item_id>/hide")
def api_hide(item_id):
    it = store.get_item(item_id)
    if not it:
        abort(404)
    store.update_item(item_id, status="hidden")
    return jsonify({"ok": True, "day": it["day"]})


@app.get("/api/status")
def api_status():
    from .llm import check
    s = _settings()
    return jsonify({
        "run_state": store.kv_get("run_state"), "last_run": store.kv_get("last_run"),
        "running": bool(_run_thread and _run_thread.is_alive()), "run_log": _run_log[-30:],
        "daemon_tick": store.kv_get("daemon_tick"), "phone": store.kv_get("phone"),
        "phone_last": store.kv_get("phone_last"), "paired": bool(s["relay"].get("key")),
        "inbox": str(config.INBOX), "llm": check(s) if request.args.get("llm") else None,
        "archive": str(archive.root(s)),
        "events": store.recent_events(25), "imports": store.recent_imports(8),
        "timezone": s.get("timezone"), "schedule": s.get("schedule"),
    })


@app.post("/api/run")
def api_run():
    global _run_thread
    j = request.get_json(silent=True) or {}
    if _run_thread and _run_thread.is_alive():
        return jsonify({"ok": False, "msg": "이미 정리 중이에요"}), 409
    _run_log.clear()

    def work():
        try:
            run(days=[j["day"]] if j.get("day") else None, publish=True, force_digest=bool(j.get("force")),
                log=lambda m: _run_log.append(str(m)))
        except Busy as e:
            _run_log.append(str(e))
        except Exception as e:
            _run_log.append(f"실패: {e}")
    _run_thread = threading.Thread(target=work, daemon=True)
    _run_thread.start()
    return jsonify({"ok": True})


@app.post("/api/import")
def api_import():
    s = _settings()
    results = []
    for f in request.files.getlist("files"):
        try:
            results.append({"ok": True, **inbox.import_upload(f.filename, f.read(), s)})
        except Exception as e:
            results.append({"ok": False, "file": f.filename, "error": str(e)})
    return jsonify({"results": results})


@app.get("/api/pairing")
def api_pairing():
    s = _settings()
    if not s["relay"].get("key"):
        s = config.update_settings({"relay": new_pairing(s["relay"].get("server") or "https://ntfy.sh")})
    code = pairing_code(s["relay"])
    import qrcode
    # QR 은 haru://pair/… — 앱의 'QR 찍기'뿐 아니라 폰 기본 카메라로 찍어도 앱이 열려 연결된다
    img = qrcode.make("haru://pair/" + code, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    apk = io.BytesIO()
    qrcode.make(APK_URL, box_size=6, border=2).save(apk, "PNG")
    return jsonify({"code": code, "qr": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
                    "server": s["relay"]["server"], "phone": store.kv_get("phone"),
                    "apk_url": APK_URL, "apk_qr": "data:image/png;base64," + base64.b64encode(apk.getvalue()).decode()})


@app.post("/api/pairing/reset")
def api_pairing_reset():
    s = _settings()
    config.update_settings({"relay": new_pairing(s["relay"].get("server") or "https://ntfy.sh")})
    store.kv_set("phone", None)
    store.kv_set("up_state", {"since": 0, "seen": []})
    return api_pairing()


@app.post("/api/publish/<day>")
def api_publish(day):
    try:
        ok = publish_day(day, _settings(), force=True)
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@app.get("/api/settings")
def api_settings():
    s = _settings()
    safe = json.loads(json.dumps(s))
    safe["relay"] = {"server": s["relay"].get("server"), "paired": bool(s["relay"].get("key"))}
    return jsonify(safe)


@app.post("/api/settings")
def api_settings_save():
    j = request.get_json(force=True)
    allowed = {"schedule", "categories", "profile", "day_boundary_hour", "timezone", "llm", "min_run_gap_min"}
    patch = {k: v for k, v in j.items() if k in allowed}
    if "relay" in j and j["relay"].get("server"):
        patch["relay"] = {"server": j["relay"]["server"].rstrip("/")}
    config.update_settings(patch)
    return api_settings()


# ---------- 노트북에서 YouTube 읽기 전용 연결 ----------
@app.get("/api/youtube")
def api_youtube():
    from .youtube import status
    return jsonify(status(_settings()))


@app.errorhandler(youtube.YouTubeError)
def _youtube_error(error):
    return jsonify({"ok": False, "msg": str(error)}), 400


@app.post("/api/youtube/client")
def api_youtube_client():
    from .youtube import configure_client
    configure_client(request.get_json())
    return jsonify({"ok": True})


@app.post("/api/youtube/connect")
def api_youtube_connect():
    from .youtube import begin_auth
    port = urlsplit(request.host_url).port or 80
    return jsonify({"url": begin_auth(port)})


@app.get("/api/youtube/oauth/callback")
def api_youtube_callback():
    from .youtube import finish_auth, YouTubeError
    import html
    try:
        finish_auth(request.args.get("state", ""), request.args.get("code", ""), bool(request.args.get("error")))
    except YouTubeError as e:
        return (f'<meta charset="utf-8"><p>{html.escape(str(e))}</p><a href="/#/youtube">하루서랍으로 돌아가기</a>', 400,
                {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})
    return redirect("/#/youtube", code=303)


@app.post("/api/youtube/disconnect")
def api_youtube_disconnect():
    from .youtube import disconnect
    disconnect()
    return jsonify({"ok": True})


@app.get("/api/youtube/playlists")
def api_youtube_playlists():
    from .youtube import list_playlists
    return jsonify({"playlists": list_playlists()})


@app.post("/api/youtube/selection")
def api_youtube_selection():
    from .youtube import save_selection
    j = request.get_json()
    save_selection(j.get("playlists", []), bool(j.get("enabled")))
    return api_youtube()


@app.post("/api/archive/<day>")
def api_archive(day):
    from .archive import export_day
    try:
        folder = export_day(day, _settings())
    except ValueError as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    except OSError as e:
        return jsonify({"ok": False, "msg": str(e)}), 500
    if folder is None:
        return jsonify({"ok": False, "msg": "저장할 보고서가 없거나 파일 보관이 꺼져 있어요"}), 404
    return jsonify({"ok": True, "path": str(folder), "url": f"/reports/{day}/보고서.html"})


@app.get("/reports/<day>/<path:filename>")
def report_file(day, filename):
    from .archive import day_dir
    if not _settings().get("archive", {}).get("enabled", True) or any(p.startswith(".") for p in Path(filename).parts):
        abort(404)
    try:
        folder = day_dir(day)
        resolved = (folder / filename).resolve()
        if not resolved.is_relative_to(folder.resolve()):
            abort(404)
        try:
            manifest = json.loads((folder / archive.MANIFEST).read_text())
        except (OSError, ValueError):
            abort(404)
        if filename not in manifest.get("files", {}):
            from . import content
            try:
                if filename not in content.allowed_files(day):
                    abort(404)
            except (OSError, ValueError, KeyError, TypeError):
                abort(404)
    except ValueError:
        abort(404)
    download = filename.startswith("원본/") and Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif"}
    return send_from_directory(folder, filename, as_attachment=download)


@app.get("/api/card/<day>/<style>.png")
def api_card(day, style):
    if style not in ("A", "B"):
        abort(404)
    dg = store.get_digest(day)
    if not dg:
        abort(404)
    # 같은 날도 보고서가 바뀌면 새 카드를 그린다 (항목 제외·AI 재분석).
    p = config.CARDS / f"{day}_v{dg['version']}_{style}.png"
    if not p.exists() or request.args.get("fresh"):
        s = _settings()
        dev = s.get("device") or {}
        render(card_from_digest(dg["data"]), style, p, int(dev.get("w", 1080)), int(dev.get("h", 2340)),
               float(dev.get("density", 3.0)))
    return send_from_directory(config.CARDS, p.name, max_age=0)


def main() -> None:
    config.ensure_dirs()
    s = _settings()
    port = int(s.get("port", 8891))
    print(f"하루서랍 대시보드: http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
