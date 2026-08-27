---
description: "이 프로젝트의 생성된 하네스를 계약에 대고 검사한다. 결정적 검사 7종."
---

`${CLAUDE_PLUGIN_ROOT}/scripts/harness_lint.py` 를 이 프로젝트 루트에 대고 실행하고,
**출력을 그대로 사용자에게 보여준다.**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness_lint.py" .
```

지적이 나오면 하나씩 고친다. 고친 뒤 **다시 돌려서 0건이 된 것을 확인**하고, 그 출력을 근거로 보고한다.
"눈으로 확인했다" 는 근거가 아니다 — 이 명령의 exit code 가 근거다.

지적 없이 통과하면 그 사실만 한 줄로 보고한다.
