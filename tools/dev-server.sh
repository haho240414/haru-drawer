#!/bin/bash
# 개발용 대시보드: 실제 데이터(~/.haru-drawer) 대신 프로젝트 안 .dev-home 을 쓴다
cd "$(dirname "$0")/.."
export HARU_HOME="$PWD/.dev-home"
export HARU_INBOX="$PWD/.dev-home/inbox"
exec ./venv/bin/python -m haru serve
