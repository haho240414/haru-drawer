"""맥↔폰 흐름: 가짜 ntfy 서버 위에서 폰 역할(Relay.send_up)을 흉내 내고 데몬·파이프라인을 돌린다."""
import base64
import io
import json
import sys
import zipfile

import pytest

from conftest import FIX, ROOT
from haru import config, crypto, relay, store

sys.path.insert(0, str(ROOT / "tools"))
import mock_ntfy  # noqa: E402


@pytest.fixture()
def ntfy():
    httpd, url = mock_ntfy.start()
    mock_ntfy.STORE.msgs.clear()
    mock_ntfy.STORE.files.clear()
    mock_ntfy.STORE.expire_attachments = False
    yield url
    httpd.shutdown()


@pytest.fixture()
def paired(home, ntfy):
    cfg = relay.new_pairing(ntfy)
    s = config.update_settings({"relay": cfg, "llm": {"backend": "fake"}})
    phone = relay.Relay(ntfy, cfg["up"], cfg["down"], cfg["key"])
    return s, phone


def png_bytes(color="red"):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (300, 500), color).save(b, "PNG")
    return b.getvalue()


def test_crypto_roundtrip_and_tamper():
    k = crypto.new_key()
    env = crypto.seal(k, "topic-a", b"hello")
    assert crypto.open_(k, "topic-a", env) == b"hello"
    with pytest.raises(crypto.CryptoError):
        crypto.open_(k, "topic-b", env)          # 다른 토픽에 붙인 봉투
    bad = bytearray(env)
    bad[-1] ^= 1
    with pytest.raises(crypto.CryptoError):
        crypto.open_(k, "topic-a", bytes(bad))   # 변조
    code = relay.pairing_code({"server": "https://ntfy.sh", "up": "u", "down": "d", "key": k}, "mac")
    assert relay.parse_pairing_code(code)["key"] == k


def test_relay_text_attachment_big(paired):
    s, phone = paired
    mac = relay.Relay.from_settings(s)
    phone.send_up({"t": "item", "id": "1", "kind": "text", "text": "짧은 글"})
    phone.send_up({"t": "item", "id": "2", "kind": "image", "name": "a.png"}, attachment=b"\x89PNG..")
    phone.send_up({"t": "item", "id": "3", "kind": "text", "text": "긴글" * 2000})   # 4KB 넘음 → 첨부로
    got = mac.poll(mac.up)
    assert [g.obj.get("id", g.obj.get("big")) for g in got] == ["1", "2", True]
    assert mac.fetch_attachment(got[1], mac.up) == b"\x89PNG.."
    assert mac.fetch_attachment(got[2], mac.up) is None and got[2].obj["id"] == "3"
    assert len(got[2].obj["text"]) == 4000


def test_daemon_receives_phone_shares(paired):
    from haru import daemon
    s, phone = paired
    phone.send_up({"t": "hello", "dev": {"w": 1080, "h": 2400, "density": 2.8125, "model": "SM-S931N"}, "tz": "Asia/Seoul", "app": "0.1"})
    phone.send_up({"t": "item", "id": "p1", "ts": "2026-10-01T09:05:00+09:00", "kind": "text",
                   "text": "https://n.news.naver.com/mnews/article/018/0006378996 기사 저장"})
    phone.send_up({"t": "item", "id": "p2", "ts": "2026-10-01T09:06:00+09:00", "kind": "image", "name": "Screenshot_1.png",
                   "mime": "image/png"}, attachment=png_bytes())
    export = (FIX / "android_self.txt").read_bytes()
    phone.send_up({"t": "item", "id": "p3", "ts": "2026-10-01T23:00:00+09:00", "kind": "export", "name": "KakaoTalkChats.txt"},
                  attachment=export)
    r = daemon.handle_phone(relay.Relay.from_settings(s), s)
    assert r["items"] == 3
    s2 = config.load_settings()
    assert s2["device"]["h"] == 2400 and s2["device"]["model"] == "SM-S931N"
    items = store.items_for_day("2026-10-01")
    assert any(i["id"] == "s:p1" and i["kind"] == "link" for i in items)
    img = [i for i in items if i["id"] == "s:p2"][0]
    assert img["kind"] == "image" and (config.MEDIA / img["media"]).exists()
    assert any(i["source"] == "kakao" for i in items)            # 폰에서 공유한 카톡 내보내기
    # 맥이 받은 것을 'ack' 로 알려 준다
    downs = phone.poll(phone.down)
    acks = [d.obj for d in downs if d.obj["t"] == "ack"]
    assert set(acks[-1]["ids"]) == {"p1", "p2", "p3"}
    assert any(d.obj["t"] == "hb" for d in downs)
    # 같은 메시지를 다시 폴링해도 두 번 처리하지 않는다
    assert daemon.handle_phone(relay.Relay.from_settings(s), s)["items"] == 0


def test_expired_attachment_is_nacked(paired):
    from haru import daemon
    s, phone = paired
    mock_ntfy.STORE.expire_attachments = True
    phone.send_up({"t": "item", "id": "old", "ts": "2026-10-01T09:06:00+09:00", "kind": "image", "name": "a.png"},
                  attachment=png_bytes())
    daemon.handle_phone(relay.Relay.from_settings(s), s)
    acks = [d.obj for d in phone.poll(phone.down) if d.obj["t"] == "ack"]
    assert acks[-1]["nack"] == ["old"] and acks[-1]["ids"] == []


def test_pipeline_fake_builds_and_publishes(paired):
    from haru import pipeline
    from haru.inbox import import_any
    s, phone = paired
    import_any(FIX / "android_self.txt", s)
    # 링크를 실제로 열지 않게 (오프라인 테스트)
    pipeline.enrich_link = lambda url: {"title": "제목 " + url[-6:], "site_kind": "web", "site": "웹"}
    res = pipeline.run(publish=True)
    assert set(res["built"]) == {"2026-09-30", "2026-10-01"}
    dg = store.get_digest("2026-10-01")["data"]
    assert dg["headline"] and dg["items"] and dg["llm"]["backend"] == "heuristic"
    assert res["published"] == ["2026-10-01"]
    msgs = [m for m in phone.poll(phone.down) if m.obj["t"] == "digest"]
    assert msgs and msgs[-1].obj["day"] == "2026-10-01"
    bundle = json.loads(phone.fetch_attachment(msgs[-1], phone.down))
    assert bundle["digest"]["day"] == "2026-10-01"
    png = base64.b64decode(bundle["cards"]["A"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    im = Image.open(io.BytesIO(png))
    assert im.size == (1080, 2340) and im.mode == "RGBA"
    # 바뀐 게 없으면 다시 보내지 않는다
    assert pipeline.run(publish=True)["published"] == []


def test_inbox_scan_moves_files(home):
    from haru import inbox
    s = config.load_settings()
    (config.INBOX / "KakaoTalkChats.txt").write_bytes((FIX / "ios_self.txt").read_bytes())
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("talk.csv", (FIX / "mac_self.csv").read_text())
    (config.INBOX / "mac.zip").write_bytes(z.getvalue())
    (config.INBOX / "shot.png").write_bytes(png_bytes("blue"))
    days = inbox.scan(s, log=lambda *_: None)
    assert "2026-10-01" in days
    assert sorted(p.name for p in (config.INBOX / "처리됨").iterdir()) == ["KakaoTalkChats.txt", "mac.zip", "shot.png"]
    assert not [p for p in config.INBOX.iterdir() if p.is_file()]


def test_hello_with_shares_publishes_latest_once(paired):
    """폰 인사와 공유가 한 바퀴에 같이 오면, 정리한 최신 날 하나만 한 번 보낸다 (예전 날 중복 X)."""
    from haru import daemon, pipeline
    from haru.inbox import import_any
    s, phone = paired
    import_any(FIX / "android_self.txt", s)            # 예전 날(9/30·10/1) 기록이 이미 있음
    pipeline.enrich_link = lambda url: {"title": "t", "site_kind": "web", "site": "웹"}
    pipeline.run(publish=False)
    phone.send_up({"t": "hello", "dev": {"w": 1080, "h": 2340}, "tz": "Asia/Seoul"})
    phone.send_up({"t": "item", "id": "n1", "ts": "2026-10-03T10:00:00+09:00", "kind": "text", "text": "새 메모 하기"})
    store.kv_set("run_request", {"force": False})      # 이번 바퀴에 정리하게
    daemon.loop_once(config.load_settings())
    digests = [m.obj["day"] for m in phone.poll(phone.down) if m.obj["t"] == "digest"]
    assert digests == ["2026-10-03"]


def test_hiding_last_item_clears_report_and_phone_card(paired):
    from haru import pipeline
    from haru.ingest import import_share
    from haru.server import app
    s, phone = paired
    import_share({"id": "only", "ts": "2026-10-03T10:00:00+09:00", "kind": "text",
                  "text": "관리사무소 전화하기"}, None, 4)
    pipeline.run(publish=True)
    initial = store.get_digest("2026-10-03")
    response = app.test_client().post("/api/item/s:only/hide")
    assert response.status_code == 200
    result = pipeline.run(days=["2026-10-03"], publish=True)
    digest = store.get_digest("2026-10-03")
    assert digest["version"] > initial["version"]
    assert digest["data"]["items"] == []
    assert digest["data"]["todos"] == []
    assert digest["data"]["lock"]["lines"] == []
    assert result["published"] == ["2026-10-03"]
    messages = [m for m in phone.poll(phone.down) if m.obj["t"] == "digest"]
    bundle = json.loads(phone.fetch_attachment(messages[-1], phone.down))
    assert bundle["digest"]["stats"]["count"] == 0
    assert bundle["digest"]["items"] == []
