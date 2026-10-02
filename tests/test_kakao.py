import io
import zipfile
from datetime import datetime

import pytest

from conftest import FIX
from haru import kakao, store
from haru.ingest import import_bundle, items_from_messages
from haru.links import find_urls, normalize, site_kind


def load(name):
    return kakao.load_path(FIX / name)


def test_detect_platforms():
    for name, plat in [("android_self.txt", "android"), ("ios_self.txt", "ios"),
                       ("windows_self.txt", "windows"), ("mac_self.csv", "mac")]:
        assert load(name).export.platform == plat, name


def test_android_parse():
    exp = load("android_self.txt").export
    assert exp.room == "나"
    ts = [m.ts for m in exp.messages]
    assert ts[0] == datetime(2026, 9, 30, 23, 58)
    assert ts[1] == datetime(2026, 10, 1, 0, 20)      # 오전 12:20 → 00:20
    assert datetime(2026, 10, 1, 12, 0) in ts           # 오후 12:00 → 12:00
    idea = [m for m in exp.messages if m.text.startswith("아이디어")][0]
    assert idea.text == "아이디어:\n1) 카톡 나에게 보내기 자동 정리\n2) 잠금화면에 요약 띄우기\n\n끝"
    blog = [m for m in exp.messages if "블로그" in m.text][0]
    assert blog.text.endswith("https://m.blog.naver.com/example_user/223456789012")
    assert not any("나갔습니다" in m.text for m in exp.messages)


def test_ios_parse():
    exp = load("ios_self.txt").export
    texts = [m.text for m in exp.messages]
    assert texts[2] == "여러 줄\n두번째 줄"
    assert exp.messages[3].ts == datetime(2026, 10, 2, 0, 5)
    assert exp.messages[4].ts == datetime(2026, 10, 2, 13, 10)


def test_windows_parse():
    exp = load("windows_self.txt").export
    assert [m.ts.hour for m in exp.messages] == [9, 12, 21, 0]
    assert exp.messages[2].text == "24시간제 시각\n이어지는 줄"
    assert exp.messages[3].ts == datetime(2026, 10, 2, 0, 1)


def test_mac_csv_parse():
    exp = load("mac_self.csv").export
    assert exp.messages[2].text == '따옴표 "인용" 과\n줄바꿈'
    assert exp.messages[0].ts == datetime(2026, 10, 1, 9, 5)   # 초는 버림 (다른 기기 내보내기와 맞추려고)
    assert exp.senders == ["나"]


def test_items_and_day_boundary(home):
    b = load("android_self.txt")
    items = items_from_messages(b.export.messages, b.media, boundary=4)
    kinds = [(i["kind"], i["day"]) for i in items]
    # 9/30 23:58 메모, 10/1 00:20 유튜브, 02:31 사진 → 새벽 4시 전이라 전부 9/30
    assert kinds[:3] == [("text", "2026-09-30"), ("link", "2026-09-30"), ("image", "2026-09-30")]
    links = [i for i in items if i["kind"] == "link"]
    assert len(links) == 4   # 유튜브, 블로그, 링크 2개 든 메시지 → 2개
    assert links[0]["url_key"] == "https://youtube.com/watch?v=dQw4w9WgXcQ"
    assert any(i["kind"] == "file" and i["meta"]["filename"] == "2026_하반기_교육계획.pdf" for i in items)
    assert not any(i["text"] == "이모티콘" for i in items)


def test_reimport_is_idempotent(home):
    r1 = import_bundle(load("android_self.txt"), boundary=4)
    r2 = import_bundle(load("android_self.txt"), boundary=4)
    assert r1["new"] == r1["items"] > 0
    assert r2["new"] == 0 and r2["dup"] == r1["items"]


def test_group_chat_rejected(home):
    with pytest.raises(ValueError):
        import_bundle(load("android_group.txt"), boundary=4)


def test_photo_filled_by_full_export(home):
    """텍스트만 내보낸 '사진' 항목이, 나중에 사진 포함 내보내기(zip)로 실제 사진을 얻는다."""
    import_bundle(load("android_self.txt"), boundary=4)
    photo = [i for i in store.items_for_day("2026-09-30") if i["kind"] == "image"][0]
    assert not photo["media"]
    # 사진 포함 내보내기: 같은 시각 메시지가 파일 이름으로 나온다
    from PIL import Image
    png = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(png, "PNG")
    txt = ("나 님과 카카오톡 대화\n저장한 날짜 : 2026년 10월 1일 오후 11:50\n\n\n"
           "2026년 10월 1일 오전 2:31, 나 : 1a2b3c4d.png\n")
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr("KakaoTalkChats.txt", txt)
        z.writestr("1a2b3c4d.png", png.getvalue())
    bundle = kakao.load_bytes("full.zip", zb.getvalue())
    r = import_bundle(bundle, boundary=4)
    assert r["media_filled"] == 1
    photo2 = store.get_item(photo["id"])
    assert photo2["media"] and photo2["media"].endswith(".png")


def test_links_normalize():
    assert normalize("https://youtu.be/abc?si=x") == normalize("https://www.youtube.com/watch?v=abc&feature=share")
    assert normalize("https://m.blog.naver.com/u/1") == normalize("https://blog.naver.com/u/1")
    assert normalize("https://youtube.com/shorts/xyz?si=1") == "https://youtube.com/watch?v=xyz"
    assert find_urls("보기(https://a.com/x_(1)) 끝.") == ["https://a.com/x_(1)"]
    assert find_urls("주소 www.naver.com, 그리고") == ["https://www.naver.com"]
    assert site_kind("https://m.blog.naver.com/u/1")[0] == "blog"
    assert site_kind("https://link.coupang.com/a/b")[0] == "shopping"
