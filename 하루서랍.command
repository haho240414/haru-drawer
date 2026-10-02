#!/bin/bash
# 더블클릭: 최신 코드로 실행본 갱신 + 상시 실행(폰 공유 받기·정해진 시각 정리) 켜기 + 대시보드 열기
cd "$(dirname "$0")"
bash tools/deploy.sh || { echo "배포 실패 — 위 메시지를 확인하세요"; read -r -p "엔터를 누르면 닫혀요"; exit 1; }
RT="$HOME/.haru-drawer"
PORT=8891
if curl -s -o /dev/null "http://127.0.0.1:$PORT/api/status"; then
  open "http://localhost:$PORT"
  echo "대시보드가 이미 켜져 있어 브라우저만 열었어요."
  exit 0
fi
(sleep 1.5 && open "http://localhost:$PORT") &
echo "하루서랍 대시보드: http://localhost:$PORT  (이 창을 닫으면 대시보드만 꺼지고, 자동 정리는 계속 돌아요)"
cd "$RT/app" && HARU_HOME="$RT" exec "$RT/venv/bin/python" -m haru serve
