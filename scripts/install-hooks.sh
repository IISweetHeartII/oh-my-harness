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
exec bash "$(git rev-parse --show-toplevel)/scripts/preflight.sh"
SH
chmod +x "$hooks/pre-push"
echo "installed: $hooks/pre-push — pushes now run scripts/preflight.sh first"
