#!/usr/bin/env bash
# pre-push 훅을 설치한다. 한 번 실행하면 그 뒤로는 push 가 preflight 를 통과해야 나간다.
#
# 왜 필요한가: 게이트를 만들어 두고 «사람이 기억해서 부르는 것» 에 맡기면, 실제로
# 그렇게 해서 실패한 가드레일이 그대로 배포됐다(v2.7.0). 기억은 배선이 아니다.
set -euo pipefail
cd "$(dirname "$0")/.."
hooks=$(git rev-parse --git-path hooks)
mkdir -p "$hooks"
cat > "$hooks/pre-push" <<'SH'
#!/usr/bin/env sh
# 무결성 확인이 먼저다 — preflight 자신이 `exit 0` 으로 바뀌었으면 그 뒤 결과는
# 전부 거짓말이다. 스크립트는 자기 종료코드를 검사할 수 없으니 밖에서 묻는다.
root=$(git rev-parse --show-toplevel)
python3 "$root/scripts/validate_repository.py" --only preflight-stages || exit 1
exec bash "$root/scripts/preflight.sh"
SH
chmod +x "$hooks/pre-push"
echo "installed: $hooks/pre-push — pushes now run scripts/preflight.sh first"
