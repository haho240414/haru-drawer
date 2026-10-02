"""CI(에뮬레이터 점검)에서 '맥' 역할. HARU_HOME 을 임시 폴더로 두고 가짜 중계 서버와 규칙 기반 분석으로 돈다.

  python tools/ci_mac.py setup <phone-server>      → 폰용 연결 코드 출력
  python tools/ci_mac.py wait-phone [초]           → 폰 인사 기다리기 (기기 정보 출력)
  python tools/ci_mac.py wait-items <개수> [초]    → 폰이 보낸 항목 기다리기
  python tools/ci_mac.py run                       → 정리 + 폰으로 보내기
  python tools/ci_mac.py dump                      → 상태 출력
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from haru import config, store  # noqa: E402
from haru.relay import new_pairing, pairing_code  # noqa: E402

MAC_SERVER = os.environ.get("HARU_CI_SERVER", "http://127.0.0.1:8899")


def handle_once() -> dict:
    from haru import daemon
    from haru.relay import Relay
    s = config.load_settings()
    try:
        return daemon.handle_phone(Relay.from_settings(s), s)
    except Exception as e:   # 중계 서버가 잠깐 안 되면 다음 바퀴에
        print(f"(중계 연결 실패: {e.__class__.__name__})", file=sys.stderr)
        return {"items": 0, "refresh": False, "resend": []}


def main(argv: list[str]) -> int:
    config.ensure_dirs()
    cmd = argv[0]
    if cmd == "setup":
        phone_server = argv[1]
        relay = new_pairing(MAC_SERVER)
        config.update_settings({"relay": relay, "llm": {"backend": "fake"}, "timezone": "Asia/Seoul"})
        print(pairing_code({**relay, "server": phone_server}, "ci-mac"))
        return 0
    if cmd == "wait-phone":
        limit = time.time() + float(argv[1] if len(argv) > 1 else 180)
        while time.time() < limit:
            handle_once()
            ph = store.kv_get("phone")
            if ph:
                print(json.dumps(ph, ensure_ascii=False))
                return 0
            time.sleep(3)
        print("폰 인사가 안 왔어요", file=sys.stderr)
        return 1
    if cmd == "wait-items":
        want = int(argv[1])
        limit = time.time() + float(argv[2] if len(argv) > 2 else 240)
        got = 0
        while time.time() < limit:
            handle_once()
            got = int(store.kv_get("phone_items_total", 0) or 0)   # 앞 단계에서 이미 받은 것도 센다
            if got >= want:
                break
            time.sleep(3)
        rows = store.db().execute("SELECT id, day, kind, source, url, substr(text,1,60) t, media FROM items").fetchall()
        for r in rows:
            print(f"ITEM kind={r['kind']} source={r['source']} media={'yes' if r['media'] else 'no'} "
                  f"day={r['day']} url={r['url'] or ''} text={(r['t'] or '').replace(chr(10), ' ')}")
        print(f"받은 항목 {got}/{want}")
        return 0 if got >= want else 1
    if cmd == "run":
        from haru.pipeline import run
        res = run(publish=True, force_digest=True)
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res.get("published") else 1
    if cmd == "dump":
        print(json.dumps({"days": store.days_with_items(), "phone": store.kv_get("phone"),
                          "events": store.recent_events(30)}, ensure_ascii=False, indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
