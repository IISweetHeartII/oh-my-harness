#!/usr/bin/env bash
# 배포 전 «모든» 게이트를 돌린다. 진짜 내용은 preflight_runner.py 에 있다.
#
# 왜 껍데기인가 (2026-08-28): 예전에는 단계를 셸에서 선언했고, 저장소 게이트가 그
# 파일을 읽어 「단계가 정말 실행되는가」를 증명하려 했다. 리뷰 열 번 동안 그 증명이
# 여섯 번 뚫렸다 — run() 중복 정의 · python3 셸 함수 · 단계 위의 exit 0 ·
# 뒤의 fail=0 · EXIT trap · `\` 로 나눈 재정의 — 그리고 `eval 'run() { …; }'` 이
# 문제의 모양을 보여 줬다. 셸이 무언가를 덮어쓰는 방법의 목록은 끝나지 않는다.
#
# 그래서 셸을 없앴다. 이 파일은 두 줄이고, `preflight-stages` 게이트가 그 두 줄을
# 글자 그대로 고정한다. 뒤엎을 셸이 남아 있지 않다.
#
# 설치형 pre-push 훅: bash scripts/install-hooks.sh
exec python3 "$(dirname "$0")/preflight_runner.py" "$@"
