# Open findings — what the adversarial reviews raised and we have not closed

두 차례 적대적 리뷰(2026-08-27)에서 나온 지적 중 **아직 안 고친 것**만 적는다.
고친 것은 CHANGELOG 에 있다. 이 파일은 «남은 빚» 하나만 담는다.

각 항목은 실측으로 재현된 것이다. 추정이 아니다.

---

## B — `~/.agents/agent-parity-check.sh`

### B-3 🔴 의미를 뒤집어도 통과한다

`Never install packages` → `Always install packages` 로 바꿔도 `scientist` 는 **98% TWIN ok**.
런타임 `name` 을 `document-specialist` → `architect` 로 바꿔도 99% 통과.

fuzzy 유사도는 «몇 글자가 같나» 를 잴 뿐 «무엇을 지시하나» 를 못 본다. 한 단어 반전은
유사도에 거의 영향이 없는데 의미는 정반대다.

**권고(Codex)**: fuzzy 를 버리고, 런타임 envelope(TOML 키·XML 태그)만 제거한 뒤
**섹션별 exact 또는 해시 비교**. 쌍둥이는 3쌍뿐이라 감당 가능한 범위다.

### B-4 실제 tracer 쌍이 이미 갈라져 있다

`~/.claude/agents/tracer.md:136` 에 `Final_Response_Contract` 가 있는데
`~/.codex/agents/tracer.toml` 에는 없다. 그런데 96% 라 `TWIN ok` 로 나온다.

즉 **지금 「드리프트 0」이라는 보고 자체가 이미 부정확하다.** B-3 을 고치면 이게 먼저 뜬다.

---

## C — `scripts/harness_lint.py`

### C-5 계약은 5섹션인데 검사는 「아무 H2 4개」

`skills/harness/SKILL.md` 의 에이전트 계약은 다섯 섹션을 요구하는데, `agent-sections` 는
H2 를 네 개 세기만 한다. 제목을 `잡담 1~4` 로 바꿔도 clean.

locale 중립을 지키면서 이걸 고치려면 **기계 판독 가능한 섹션 마커**가 필요하다
(예: `## 핵심 역할 <!--harness:role-->`). 그건 팩토리가 생성하는 형식을 바꾸는 일이라
기존 하네스의 마이그레이션 경로가 같이 필요하다.

### C-8 `.claude/workflows/*.ts` 를 안 읽는다

Workflow 스크립트에서만 호출되는 에이전트가 **고아로 오진**되고, 반대로 workflow 안의
존재하지 않는 에이전트 호출은 **안 잡힌다**. v2 의 주력 실행 모드가 Workflow 인데
린터가 그 파일을 아예 안 본다.

### C-11 `model-tiering` 은 관찰 불가능한 것을 판정한다

「근거 있는 opus 고정」과 「무근거 일괄 고정」을 코드로 구분할 방법이 없다.
**Codex 권고: 삭제하거나 advisory 로 강등.** 지금은 findings 로 나가 CI 를 막는다.

---

## A — `~/.agents/skill-reach-check.sh`

### A-9 다른 루트의 동명이인이 통과한다

`/foo/SKILL.md` 접미사만 보므로, 공유 루트가 아닌 `r9/foo/SKILL.md` 가 등록돼 있으면
공유 루트의 `foo` 가 도달했다고 판정한다. 루트 prefix 까지 봐야 한다.

### A-11 새 팩을 기대 집합에 학습하지 않는다

`.skill-reach-expected` 는 최초 실행 시점의 목록에서 자라지 않는다. 23번째 팩을 추가했다가
삭제해도 감지 못 한다. 추가는 자동 학습하되 «삭제만» 위반으로 볼지, 추가도 확인을 받을지
정해야 한다.

### A-12 Claude 쪽은 SKILL.md 가 «파일인지» 만 본다

빈 파일, 깨진 frontmatter, 다른 유효 타깃으로 바뀐 symlink 는 전부 통과한다.

---

## D — `tests/guardrail/run_guardrail.py`

### D-3 working tree 를 복사한다 (index 가 아니라)

`copy_tree` 가 워킹트리를 복사한 뒤 `git init && git add -A` 한다. 그래서 원본에
untracked 파일이 있어도 복사본에서는 tracked 가 되고, `fixtures-tracked` 가 과거 CI 실패를
그대로 놓친다. **`git archive HEAD` 로 index 기반 복제**가 맞다.

### D-4 정상 YAML 표현 변형에 깨진다

breaker 가 `name: harness` 라는 정확한 문자열을 치환하는데, 픽스처가 `name: "harness"` 로
바뀌면 치환이 안 돼 거짓 실패가 난다. 픽스처 표현에 결합돼 있다.

### D-5 개수 표기가 부정확하다

"12 repository checks" 라고 찍지만 `dead-api-yaml` 은 `dead-api` 의 다른 입력일 뿐 별도
게이트가 아니다. 실제로는 **11 규칙 + 캐리어 케이스 1**.

### D-6 유효 변형 `uniform-sonnet` 은 아무것도 검증하지 않는다

에이전트가 2개인데 `model-tiering` 은 `<3` 이면 조기 반환한다. 그래서 이 «유효 변형 통과»
증명은 규칙을 한 줄도 안 타고 있다. 에이전트를 3개로 늘려야 의미가 생긴다.

---

## 아직 거부되는 정상 하네스 (거짓양성 후보)

- Workflow 에서만 에이전트를 호출하는 하네스 (C-8)
- 근거를 각각 기록한 3개 all-opus 전문가 하네스 (C-11)
- 의도적인 project-scope override
- 중립적인 API 역사 서술 중 일부 표현
- 인용부호·다중행 등 정상 YAML 변형 (D-4)

---

## 우선순위

1. **D-6** — 유효 변형 하나가 검증을 안 하고 있다. 가장 싸고, 「증명했다」는 주장에 직결
2. **D-3** — index 기반 복제. `fixtures-tracked` 가 실제로는 안 돌고 있다
3. **C-11** — advisory 강등 또는 삭제. 관찰 불가능한 것을 CI 로 막고 있다
4. **B-3/B-4** — 섹션별 비교로 재작성. 현재 「드리프트 0」 보고가 부정확하다
5. **C-8** — Workflow 파일 독해. v2 주력 모드인데 사각지대
6. A-9 / A-11 / A-12 / C-5 / D-4 / D-5
