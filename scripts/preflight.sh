#!/usr/bin/env bash
# 배포 전 «모든» 게이트를 돌린다. 하나라도 실패하면 non-zero.
#
# 왜 있는가 (2026-08-27): `validate_repository.py && git commit && git push` 라고
# 썼더니 «가드레일 실패» 가 체인에 없어서 그대로 배포됐다. 검사를 여러 개 만들어
# 놓고 배포 명령에 하나만 걸면, 나머지는 있으나 마나다.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
run() { printf '\n== %s\n' "$1"; shift; "$@" || fail=1; }
run "repository gates"  python3 scripts/validate_repository.py
run "guardrail suite"   python3 tests/guardrail/run_guardrail.py
run "reference harness" python3 scripts/harness_lint.py tests/fixtures/clean-harness
[ $fail -eq 0 ] && echo && echo "preflight: all gates green" || { echo; echo "preflight: FAILED — do not push"; }
exit $fail
