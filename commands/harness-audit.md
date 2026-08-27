---
description: "이 프로젝트에 하네스가 있는지, 문서와 실물이 일치하는지 감사한다."
---

`harness` 스킬의 **Phase 0(현황 감사)** 만 수행한다. 새로 만들거나 고치지 않는다.

1. `프로젝트/.claude/agents/`, `프로젝트/.claude/skills/`, `프로젝트/CLAUDE.md` 를 읽는다
2. `~/.claude/agents/`, `~/.claude/skills/` 유저 스코프도 읽어 **이름 충돌**을 본다
3. CLAUDE.md 기록과 실물 목록을 대조해 불일치(drift)를 찾는다
4. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness_lint.py" .` 를 돌려 결정적 검사 결과를 붙인다
5. 감사 결과만 보고한다 — **조치는 사용자 승인 후**

v1 잔재(`TeamCreate`/`TeamDelete`/실험 플래그)가 있으면
`skills/harness/references/execution-modes.md` 의 마이그레이션 절차를 안내한다.
