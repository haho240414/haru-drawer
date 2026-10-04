"""명령줄: python -m haru <명령>

  import <파일|폴더>...   카톡 내보내기(.txt/.csv/.zip/폴더)나 사진 넣기
  run [--day YYYY-MM-DD] [--force] [--no-publish]   정리 한 번 돌리기
  serve                   대시보드 (http://localhost:8891)
  daemon                  상시 실행 (폰 공유 받기·받은편지함 감시·정해진 시각 정리)
  pair [--reset]          폰 연결 코드 보기
  status                  상태
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, store


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="haru", description="하루서랍")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import")
    p.add_argument("paths", nargs="+")
    p.add_argument("--allow-group", action="store_true")
    p = sub.add_parser("run")
    p.add_argument("--day", action="append")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-publish", action="store_true")
    p = sub.add_parser("export", help="분석된 보고서를 날짜별 노트북 파일로 저장 (AI 재호출 없이)")
    p.add_argument("--day", action="append")
    p.add_argument("--output", type=Path)
    sub.add_parser("serve")
    sub.add_parser("daemon")
    p = sub.add_parser("pair")
    p.add_argument("--reset", action="store_true")
    sub.add_parser("status")
    p = sub.add_parser("content", help="완성한 공개 영상 자료를 블로그 초안·대표 이미지 작업으로 연결")
    p.add_argument("action", choices=["status", "build", "attach-image"])
    p.add_argument("--day")
    p.add_argument("--signature", help="이미지가 만들어진 작업의 signature")
    p.add_argument("--file", type=Path, help="생성된 대표 이미지")
    p = sub.add_parser("transcribe", help="지정한 날짜의 YouTube 전체 음성 확보·전사 후 보고서 재작성")
    p.add_argument("--day", required=True)
    p.add_argument("--id", help="특정 항목만 처리")
    p.add_argument("--no-publish", action="store_true")
    p = sub.add_parser("youtube", help="YouTube 계정 상태·재생목록 조회·새 저장분 수집")
    p.add_argument("action", choices=["status", "playlists", "sync", "snapshot", "due", "done"])
    p.add_argument("--file", type=Path, help="로그인된 브라우저에서 확인한 전체 목록 JSON")
    p.add_argument("--day", help="done에 기록할 최초 due의 날짜 (자정을 넘긴 작업용)")
    a = ap.parse_args(argv)
    config.ensure_dirs()
    settings = config.load_settings()
    if a.cmd == "content":
        from . import content
        if a.action != "status" and not a.day:
            ap.error("content build/attach-image에는 --day가 필요해요")
        if a.action == "attach-image" and (not a.file or not a.signature):
            ap.error("attach-image에는 --file과 --signature가 필요해요")
        try:
            result = (content.status(a.day, settings) if a.day else
                      {"enabled": bool(settings.get("content", {}).get("enabled")), "pending": content.pending(settings)}) if a.action == "status" else (
                content.build(a.day, settings) if a.action == "build" else content.attach_image(a.day, a.signature, a.file, settings))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        except (ValueError, OSError, KeyError) as e:
            print(str(e), file=sys.stderr)
            return 1
        except Exception as e:
            from .llm import LLMError
            if not isinstance(e, LLMError):
                raise
            print(str(e), file=sys.stderr)
            return 1
    if a.cmd == "transcribe":
        from .transcribe import queue_day
        from .pipeline import run, run_lock
        if not settings.get("transcription", {}).get("enabled"):
            print("로컬 음성 전사 환경을 먼저 설정해야 해요", file=sys.stderr)
            return 1
        with run_lock():
            count = queue_day(a.day, a.id)
        if not count:
            print("처리할 YouTube 영상이 없어요", file=sys.stderr)
            return 1
        result = run(days=[a.day], publish=not a.no_publish, force_digest=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    if a.cmd == "youtube":
        from . import youtube
        try:
            if a.action == "snapshot" and not a.file:
                ap.error("youtube snapshot에는 --file이 필요해요")
            if a.day and a.action != "done":
                ap.error("youtube --day는 done에만 사용할 수 있어요")
            result = {"status": lambda: youtube.status(settings), "playlists": youtube.list_playlists,
                      "sync": lambda: youtube.sync(settings),
                      "due": lambda: youtube.browser_due(settings), "done": lambda: youtube.browser_done(a.day),
                      "snapshot": lambda: youtube.import_browser_snapshot(json.loads(a.file.read_text("utf-8")), settings)}[a.action]()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if isinstance(result, dict) and result.get("errors") else 0
        except youtube.YouTubeError as e:
            print(str(e), file=sys.stderr)
            return 1

    if a.cmd == "import":
        from .inbox import import_any
        for raw in a.paths:
            path = Path(raw).expanduser()
            res = import_any(path, settings, allow_group=a.allow_group)
            print(json.dumps(res, ensure_ascii=False))
        return 0
    if a.cmd == "run":
        from .pipeline import run
        res = run(days=a.day, publish=not a.no_publish, force_digest=a.force)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["ok"] else 1
    if a.cmd == "export":
        from .archive import export_day
        if a.output:
            settings["archive"] = {"enabled": True, "directory": str(a.output.expanduser().resolve())}
        days = a.day or [d[0] for d in store.db().execute("SELECT day FROM digests ORDER BY day")]
        for day in days:
            folder = export_day(day, settings)
            print(json.dumps({"day": day, "path": str(folder) if folder else None}, ensure_ascii=False))
        return 0
    if a.cmd == "serve":
        from .server import main as serve
        serve()
        return 0
    if a.cmd == "daemon":
        from .daemon import main as daemon
        daemon()
        return 0
    if a.cmd == "pair":
        from .relay import new_pairing, pairing_code
        if a.reset or not settings["relay"].get("key"):
            settings = config.update_settings({"relay": new_pairing(settings["relay"].get("server") or "https://ntfy.sh")})
        print(pairing_code(settings["relay"]))
        return 0
    if a.cmd == "status":
        print(json.dumps({"days": store.days_with_items(10), "last_run": store.kv_get("last_run"),
                          "phone": store.kv_get("phone")}, ensure_ascii=False, indent=1))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
