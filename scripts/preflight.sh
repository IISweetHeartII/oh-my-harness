#!/usr/bin/env bash
# 배포 전 «모든» 게이트를 돌린다. 하나라도 실패하면 non-zero.
#
# 왜 있는가 (2026-08-27): `validate_repository.py && git commit && git push` 라고
# 썼더니 «가드레일 실패» 가 체인에 없어서 그대로 배포됐다. 검사를 여러 개 만들어
# 놓고 배포 명령에 하나만 걸면, 나머지는 있으나 마나다.
#
# 그리고 이 파일은 **CI 가 실제로 부르는 것과 같아야** 한다. CI 가 개별 검사를
# 따로 나열하면 두 목록이 갈라지고, 그때 초록불은 «여기 있는 게이트가 통과했다»
# 가 아니라 «CI 가 아는 게이트만 통과했다» 가 된다. 그래서 CI 는 이 스크립트를
# 부르고, `ci-runs-preflight` 게이트가 그 사실을 검사한다.
#
# 설치형 pre-push 훅: bash scripts/install-hooks.sh
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
run() { printf '\n== %s\n' "$1"; shift; "$@" || fail=1; }

# 판정기부터 시험한다. 이게 틀리면 그 아래 «ok» 전부가 거짓말이고, 실제로
# `verdict()` 의 exit-2 보호를 지우면 자기시험만 실패하고 preflight 는 통과했다 —
# 자기시험이 강제 경로에 연결돼 있지 않았다.
run "guardrail self-test" python3 tests/guardrail/run_guardrail.py --self-test
run "repository gates"  python3 scripts/validate_repository.py
run "guardrail suite"   python3 tests/guardrail/run_guardrail.py
run "reference harness" python3 scripts/harness_lint.py tests/fixtures/clean-harness

# 하네스가 없는 곳에 대고 돌리면 «깨끗함» 이 아니라 «잴 것이 없음»(2) 이어야 한다.
printf '\n== nothing-to-lint returns 2, not 0\n'
empty=$(mktemp -d)
python3 scripts/harness_lint.py "$empty" >/dev/null 2>&1
rc=$?; rmdir "$empty"
if [ "$rc" = 2 ]; then echo "  ok  exit 2"; else echo "  FAIL exit $rc"; fail=1; fi

printf '\n== every JSON parses\n'
python3 - <<'PY' || fail=1
import json, sys
from pathlib import Path
bad = []
for path in sorted(Path('.').rglob('*.json')):
    if any(p in {'.git', 'node_modules', '.omc'} for p in path.parts):
        continue
    try:
        json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        bad.append(f'{path}: {exc}')
if bad:
    sys.exit('Invalid JSON:\n' + '\n'.join(bad))
print('  ok  all JSON files parse')
PY

printf '\n== no merge conflict markers\n'
python3 - <<'PY' || fail=1
import sys
from pathlib import Path
# '=======' 단독은 Markdown setext 밑줄이기도 하다. 여는/닫는 표식이 같은 파일에
# 있을 때만 충돌로 본다 — 산문은 그런 짝을 만들지 않는다.
OPEN, MID, CLOSE = '<<<<<<< ', '=======', '>>>>>>> '
SUFFIXES = {'.md', '.json', '.yml', '.yaml', '.py'}
offenders = []
for path in sorted(Path('.').rglob('*')):
    if not path.is_file() or path.suffix.lower() not in SUFFIXES:
        continue
    if any(p in {'.git', 'node_modules', '.omc'} for p in path.parts):
        continue
    lines = path.read_text(encoding='utf-8', errors='ignore').splitlines()
    has_bracket = any(l.startswith(OPEN) or l.startswith(CLOSE) for l in lines)
    for n, line in enumerate(lines, 1):
        if line.startswith(OPEN) or line.startswith(CLOSE):
            offenders.append(f'{path}:{n}:{line}')
        elif has_bracket and line.rstrip() == MID:
            offenders.append(f'{path}:{n}:{line}')
if offenders:
    sys.exit('Merge conflict markers found:\n' + '\n'.join(offenders))
print('  ok  no merge conflict markers')
PY

[ $fail -eq 0 ] && { echo; echo "preflight: all gates green"; } || { echo; echo "preflight: FAILED — do not push"; }
exit $fail
