# 하루서랍

카톡 **'나에게 보내기'(나와의 채팅)** 로 모은 링크·캡처·메모를 하루 단위로 AI 가 분석해
**보고서**로 정리하고, 요약 카드를 **폰 잠금화면**에 띄운다.

```
 폰                                   맥 (이 저장소의 haru/ 엔진)
 ─────────────────────────            ─────────────────────────────────────
 카톡 나와의 채팅 ─ 내보내기 ─┐        받기: 카톡 내보내기(.txt/.csv/.zip) · 폰 공유 · ~/하루서랍 폴더
 아무 앱 '공유 → 하루서랍' ───┼─암호화─▶ 내용 가져오기: 링크 본문·유튜브 자막·네이버 블로그·PDF
                              │  중계   분석: Codex(ChatGPT 구독)로 항목별 요약·의도·할 일 + 캡처 글자 읽기
 잠금화면 배경 + 조용한 알림 ◀─┴(ntfy)─ 하루 보고서 + 잠금화면 카드(A 카드형 / B 큰 글씨) PNG
```

## 쓰는 법

1. 맥: `하루서랍.command` 더블클릭 → 대시보드 http://localhost:8891 (상시 실행도 함께 켜짐)
2. 폰: [haru-drawer.apk](https://github.com/haho240414/haru-drawer/releases/latest/download/haru-drawer.apk) 설치 → **맥 연결 → QR 찍기**
   (대시보드 '폰 연결' 화면의 QR. 폰 기본 카메라로 찍어도 앱이 열려 연결됨)
3. 모으기 — 둘 중 편한 것
   - 지금처럼 **카톡 나에게 보내기** → 저녁에 한 번 나와의 채팅 ≡ → ⚙ → **대화 내용 내보내기** → '텍스트 메시지만 보내기' → **하루서랍** 선택
     (맥 카톡에서 내보내 `~/하루서랍` 폴더에 저장해도 됨. 같은 대화를 여러 번 넣어도 겹치지 않음)
   - 아니면 아무 앱에서 **공유 → 하루서랍** (카톡 대신. 내보내기 없이 자동, 캡처 원본까지)
4. 정해진 시각(08:00 · 12:30 · 18:30 · 22:00)마다, 그리고 폰 공유가 잠잠해지면 정리 → 폰 잠금화면이 바뀜

## 구성

| 경로 | 내용 |
|---|---|
| `haru/kakao.py` | 카톡 내보내기 4형식(안드로이드·아이폰·윈도 txt, 맥 csv) + 사진 포함 zip/폴더 |
| `haru/ingest.py` | 메시지 → 항목 (링크마다 하나, 분 단위 시각+내용 ID 로 중복 제거, 새벽 4시 경계) |
| `haru/enrich.py` | 링크 내용: 일반 기사(trafilatura)·네이버 블로그(모바일 본문)·유튜브(yt-dlp 자막)·SNS(카톡 미리보기와 같은 글) |
| `haru/analyze.py` | 항목 분석(5개씩 묶어 Codex, 캡처는 이미지로 첨부) → 하루 보고서(핵심 3·할 일·주제·나중에 볼 것) |
| `haru/lockcard.py` | 잠금화면 카드: `app/lockcard.html` 을 헤드리스 크롬으로 폰 해상도 투명 PNG |
| `haru/relay.py` `crypto.py` | ntfy.sh 중계 + AES-256-GCM (키는 페어링 QR 로만 폰에) |
| `haru/daemon.py` | 상시 실행: 폰 메시지·받은편지함·정해진 시각 |
| `haru/server.py` + `app/` | 대시보드. `app/` 은 폰 앱 화면과 같은 코드 (Capacitor) |
| `android/` | 폰 앱: 공유 받기(ShareActivity)·주고받기(SyncEngine/WorkManager)·잠금화면(Lockscreen)·플러그인(HaruPlugin) |

## 개인정보

- 카톡 내용·분석 결과·사진은 **맥(~/.haru-drawer)과 폰에만** 저장된다. 이 저장소엔 코드와 가짜 시험 데이터뿐.
- 맥↔폰은 ntfy.sh(무료 공개 중계)를 거치지만 **내용은 맥·폰만 아는 키로 암호화**돼 중계 서버는 못 읽는다.
- 분석은 맥의 Codex CLI(ChatGPT 구독)로 한다 → 항목 내용이 OpenAI 로 전송된다. 원치 않으면 설정에서 ollama(이 맥 로컬 모델)로.
- 다른 사람이 있는 대화방 내보내기는 받지 않는다 (나와의 채팅만).

## 개발

```bash
python3.11 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python -m pytest -q tests          # 엔진 테스트 (가짜 ntfy 서버 tools/mock_ntfy.py)
venv/bin/python -m haru import 내보내기.txt  # 넣기
venv/bin/python -m haru run                 # 정리 한 번
```

APK 는 GitHub Actions 가 빌드한다(이 맥엔 자바 없음): 엔진 테스트 → 빌드 + 암호 호환 단위 테스트(파이썬이 만든 봉투를 코틀린이 여는지)
→ 에뮬레이터(API 34·36) 전 과정 점검 `.github/scripts/e2e.sh` (연결 → 링크·캡처·카톡 내보내기 공유 → 맥 정리 → 폰 잠금화면 스크린숏) → Releases.

서명 키: `android-signing/`(git 제외) + 저장소 비밀값 `ANDROID_KEYSTORE_BASE64`/`ANDROID_KEYSTORE_PASSWORD`. 잃으면 기존 앱 위 업데이트 불가.
