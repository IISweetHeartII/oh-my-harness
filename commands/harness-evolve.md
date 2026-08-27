---
description: "하네스를 쓴 결과를 회고하고 에이전트·스킬·오케스트레이터에 되먹인다."
---

`evolve` 스킬을 호출한다 (`/oh-my-harness:evolve`).

반영이 끝나면 **반드시** 검증으로 닫는다:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness_lint.py" .
```

진화는 파일을 고치는 일이므로, 고친 뒤 계약이 깨졌는지 확인하지 않으면
«개선했다» 는 주장이 근거 없는 말이 된다.
