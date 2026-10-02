#!/bin/bash
# 실행본 배포: 코드를 ~/.haru-drawer/app 으로 복사 → 실행용 venv → launchd 상시 실행(데몬) 등록·재시작.
# ~/Documents 는 macOS 개인정보 보호(TCC)로 백그라운드 프로세스가 못 읽어서 실행본을 홈의 숨김 폴더에 둔다.
#   tools/deploy.sh          배포 + 데몬 켜기
#   tools/deploy.sh off      데몬 끄기 (자동 정리 멈춤)
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
RT="$HOME/.haru-drawer"
LABEL="com.yunhojun.haru-drawer"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UIDN="$(id -u)"

if [ "${1:-}" = "off" ]; then
  launchctl bootout "gui/$UIDN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "하루서랍 상시 실행을 껐어요"
  exit 0
fi

mkdir -p "$RT/app" "$RT/logs" "$HOME/하루서랍"
rsync -a --delete --exclude venv --exclude .venv --exclude node_modules --exclude android --exclude .git \
  --exclude .dev-home --exclude android-signing --exclude tests --exclude .github --exclude dist \
  "$SRC/haru" "$SRC/app" "$SRC/requirements.txt" "$RT/app/"

PY311="$(command -v python3.11 || true)"
[ -z "$PY311" ] && [ -x "$HOME/.local/bin/python3.11" ] && PY311="$HOME/.local/bin/python3.11"
if [ ! -x "$RT/venv/bin/python" ]; then
  echo "실행용 파이썬 환경 만드는 중 (처음 한 번, 1~2분)…"
  "${PY311:-python3}" -m venv "$RT/venv"
fi
REQ_HASH="$(shasum "$RT/app/requirements.txt" | cut -c1-12)"
if [ "$(cat "$RT/venv/.req" 2>/dev/null || true)" != "$REQ_HASH" ]; then
  "$RT/venv/bin/pip" install -q --upgrade pip
  "$RT/venv/bin/pip" install -q -r "$RT/app/requirements.txt"
  echo "$REQ_HASH" > "$RT/venv/.req"
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$RT/venv/bin/python</string><string>-m</string><string>haru</string><string>daemon</string></array>
  <key>WorkingDirectory</key><string>$RT/app</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HARU_HOME</key><string>$RT</string>
    <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$RT/logs/launchd.out</string>
  <key>StandardErrorPath</key><string>$RT/logs/launchd.err</string>
</dict>
</plist>
EOF
launchctl bootout "gui/$UIDN/$LABEL" 2>/dev/null || true
# 바로 다시 등록하면 아직 내려가는 중이라 'Input/output error' 가 난다 → 완전히 내려갈 때까지 기다림
for _ in $(seq 1 20); do launchctl print "gui/$UIDN/$LABEL" >/dev/null 2>&1 || break; sleep 0.5; done
launchctl bootstrap "gui/$UIDN" "$PLIST" 2>/dev/null || { sleep 2; launchctl bootstrap "gui/$UIDN" "$PLIST"; }
echo "하루서랍 상시 실행 켜짐 (로그: $RT/logs/daemon.log)"
