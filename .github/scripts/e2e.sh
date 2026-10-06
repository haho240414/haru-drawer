#!/usr/bin/env bash
# 에뮬레이터 전 과정 점검 (맥 역할 = 이 CI 머신의 파이썬 엔진, 중계 = 가짜 ntfy 10.0.2.2:8899)
#  1 연결(딥링크 haru://pair/…) → 폰 인사(화면 크기)
#  2 공유 3종: 링크 글 · 캡처(이미지) · 카톡 대화 내보내기(txt) → 맥이 받고 ack
#  3 맥 정리(규칙 기반) → 폰으로 보고서·카드 → 폰 저장 → 잠금화면 배경·알림 → 잠금화면 스크린숏
set -uo pipefail
APK="$1"; OUT="$2"; PKG=io.github.haho240414.harudrawer
mkdir -p "$OUT"
A() { timeout 90 adb "$@"; }
PY="${PYTHON:-python3}"
export HARU_HOME="$PWD/.ci-home" HARU_INBOX="$PWD/.ci-home/inbox"
FAIL=0
step() { echo; echo "===== $*"; }
check() { if eval "$2"; then echo "✓ $1"; else echo "✗ $1"; FAIL=1; fi; }

step "설치"
A install -r -g "$APK" || exit 1
A shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS || true
A shell dumpsys deviceidle whitelist +"$PKG" || true
A shell settings put system screen_off_timeout 600000
A shell input keyevent 224
A shell wm dismiss-keyguard || true
A logcat -c

step "1. 연결"
CODE="$($PY tools/ci_mac.py setup http://10.0.2.2:8899)"
echo "연결 코드: ${CODE:0:40}…"
for TRY in 1 2 3; do
  A shell am start -W -a android.intent.action.VIEW -d "haru://pair/$CODE" "$PKG"
  sleep 3
  PID="$(A shell pidof "$PKG" | tr -d '\r')"
  [ -n "$PID" ] && break
done
$PY tools/ci_mac.py wait-phone 150 | tee "$OUT/phone.json"
check "폰이 맥에 인사함 (화면 크기 전달)" '[ -s "$OUT/phone.json" ] && grep -q "\"w\"" "$OUT/phone.json"'
sleep 15   # CI 에뮬레이터(소프트웨어 그리기)는 웹 화면이 10초 넘게 걸려 뜬다
A exec-out screencap -p > "$OUT/1_app_paired.png"

step "2. 공유 3종"
# (가) 링크 글 — 크롬에서 공유하듯 EXTRA_SUBJECT + EXTRA_TEXT
A shell am start -W -a android.intent.action.SEND -t text/plain \
  --es android.intent.extra.SUBJECT "'카톡 내보내기 뷰어'" \
  --es android.intent.extra.TEXT "https://github.com/zeikar/kakaotalk-viewer" \
  -n "$PKG/.ShareActivity"
sleep 2
# (나) 캡처 · (다) 카톡 '나와의 채팅' 내보내기 txt
# adb 셸은 갤러리·다운로드 파일 읽기 권한을 남의 앱에 못 넘겨줘서(SecurityException — 첫 점검에서 확인),
# 실제 앱처럼 FileProvider 주소 + 읽기 권한을 붙여 보내는 점검용 화면(TestSendActivity, 디버그 빌드에만)으로 보낸다
A shell screencap -p /data/local/tmp/haru_capture.png
A push tests/fixtures/android_self.txt /data/local/tmp/KakaoTalkChats.txt
A shell chmod 644 /data/local/tmp/haru_capture.png /data/local/tmp/KakaoTalkChats.txt
A shell run-as "$PKG" sh -c "'mkdir -p cache/share && cp /data/local/tmp/haru_capture.png /data/local/tmp/KakaoTalkChats.txt cache/share/ && ls -la cache/share'"
A shell am start -W -n "$PKG/.TestSendActivity" --es file share/haru_capture.png --es mime image/png
sleep 3
A shell am start -W -n "$PKG/.TestSendActivity" --es file share/KakaoTalkChats.txt --es mime text/plain
sleep 3
A shell am start -W -a android.intent.action.VIEW -d "haru://sync" "$PKG"
$PY tools/ci_mac.py wait-items 3 240 | tee "$OUT/items.txt"
check "맥이 공유 3건 받음" 'grep -q "받은 항목 [3-9]" "$OUT/items.txt"'
check "링크 항목" 'grep -q "kind=link source=share.*github.com/zeikar" "$OUT/items.txt"'
check "캡처 항목(사진 파일 있음)" 'grep -q "kind=image source=share media=yes" "$OUT/items.txt"'
check "카톡 내보내기 항목" 'grep -q "source=kakao" "$OUT/items.txt"'

step "3. 맥 정리 → 폰"
$PY tools/ci_mac.py run | tee "$OUT/run.json"
check "보고서를 폰으로 보냄" 'grep -q "\"published\": \[\"" "$OUT/run.json"'
A shell am start -W -a android.intent.action.VIEW -d "haru://sync" "$PKG"
GOT=""
for _ in $(seq 1 40); do
  sleep 3
  GOT="$(A shell run-as "$PKG" ls files/digests 2>/dev/null | tr -d '\r' | grep json || true)"
  [ -n "$GOT" ] && break
  A shell am start -a android.intent.action.VIEW -d "haru://sync" "$PKG" >/dev/null 2>&1
done
echo "폰에 저장된 보고서: $GOT"
check "폰이 보고서 저장" '[ -n "$GOT" ]'
sleep 4
A shell run-as "$PKG" cat shared_prefs/haru.xml > "$OUT/prefs.xml" 2>/dev/null || true
check "잠금화면 배경 적용 기록" 'grep -q "appliedKey" "$OUT/prefs.xml"'
A shell dumpsys notification --noredact > "$OUT/notifications.txt" 2>&1 || true
check "잠금화면 알림" 'grep -q "$PKG" "$OUT/notifications.txt"'
A shell dumpsys wallpaper > "$OUT/wallpaper.txt" 2>&1 || true

step "4. 화면"
A shell am start -W -n "$PKG/.MainActivity"
sleep 15
A exec-out screencap -p > "$OUT/2_app_report.png"
# 알림과 동일한 보고서 딥링크: 이미 열린 앱 + 종료된 앱에서 날짜를 소비해 해당 보고서로 이동.
DAY="$(printf '%s\n' "$GOT" | head -1 | sed 's/\.json$//')"
A shell am start -W -a android.intent.action.VIEW -d "haru://report/$DAY" "$PKG"
sleep 5
A exec-out screencap -p > "$OUT/2_report_link_warm.png"
A shell am force-stop "$PKG"
A shell am start -W -a android.intent.action.VIEW -d "haru://report/$DAY" "$PKG"
sleep 15
A exec-out screencap -p > "$OUT/2_report_link_cold.png"
OPENED="$(A logcat -d -s HaruPlugin:I | grep -c "보고서 열기: $DAY" || true)"
check "알림 보고서 목적지가 앱 실행 중·종료 후 각각 처리됨" '[ "$OPENED" = "2" ]'
A shell dumpsys activity intents > "$OUT/report_intents.txt" 2>&1 || true
check "보고서 알림 PendingIntent가 날짜를 포함" 'grep -q "haru://report/$DAY" "$OUT/report_intents.txt"'
# 재연결 확인: 화면을 다시 띄워도 연결 딥링크를 또 처리하지 않아야 한다
RELINK="$(A logcat -d -s HaruLinks:I | grep -c '연결:' || true)"
echo "연결 처리 횟수: $RELINK"
check "연결 딥링크는 한 번만 처리 (배경 바꿀 때 화면이 다시 만들어져도)" '[ "$RELINK" = "1" ]'
# PIN 을 걸어 잠금화면이 반드시 뜨게 → 끄고 켜서 찍기
A shell locksettings set-pin 1234 || true
A shell input keyevent 223
sleep 3
A shell input keyevent 224
sleep 3
A exec-out screencap -p > "$OUT/3_lockscreen.png"
A shell input keyevent 223
sleep 1
A shell input keyevent 224
sleep 2
A exec-out screencap -p > "$OUT/3_lockscreen_again.png"
A shell locksettings clear --old 1234 || true

$PY tools/ci_mac.py dump > "$OUT/mac_state.json" || true
A logcat -d > "$OUT/logcat.txt"
grep -E "Haru(Sync|Lock|Share|Links|Plugin)|AndroidRuntime" "$OUT/logcat.txt" | tail -80 || true
echo
echo "===== 점검 결과: $([ $FAIL = 0 ] && echo 통과 || echo 실패)"
exit $FAIL
