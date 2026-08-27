---
name: build
description: "청구 하네스 오케스트레이터. '청구 하네스 실행', '요금 반영해줘' 요청 시."
---

# Build — 청구 오케스트레이터

## 실행 모드: 서브에이전트 위임

Phase 1: `Agent(subagent_type: "billing-analyst")` 로 규칙 추출
Phase 2: `Agent(subagent_type: "billing-builder")` 로 구현
