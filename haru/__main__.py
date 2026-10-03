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
    a = ap.parse_args(argv)
    config.ensure_dirs()
    settings = config.load_settings()

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
        return 0
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
