<!-- Modified from revfactory/harness (Apache-2.0, Copyright 2025 robin).
     Upstream's four principles, PR checklist and issue guidance are kept as
     written. Added: the preflight entry point, what each gate answers, how to
     add a rule, and attribution rules. Changed: the response-time promise,
     which this fork cannot honour and should not inherit. -->

# Contributing to oh-my-harness

기여를 환영합니다. 이 문서는 짧습니다 — 규칙보다 원칙을 따릅니다.

## 원칙

1. **스킬은 에이전트를 위한 지시서다.** 사용자용 설명서·마케팅 문구·Claude가 이미 아는 일반 지식은 스킬에 넣지 않는다.
2. **컨텍스트는 공공재다.** SKILL.md 본문 500줄 이내, 세부는 `references/`로. 모든 문장이 토큰 비용을 정당화해야 한다.
3. **Why를 설명한다.** "ALWAYS/NEVER" 대신 이유를 쓴다. 이유를 알면 엣지 케이스에서도 올바르게 판단한다.
4. **현행 런타임만 참조한다.** 실험 플래그, 제거된 API(`TeamCreate` 등), 특정 모델 하드코딩을 PR에 넣지 않는다. 런타임 변경으로 문서가 깨지면 그것이 최우선 수정 대상이다.

원칙 4는 이제 사람이 기억하지 않아도 된다 — `dead-api` 게이트가 검사한다.

## 명령 하나

```bash
python3 -m pip install pyyaml     # 한 번만 — CI 계약 게이트가 워크플로우를 «파싱» 한다
bash scripts/preflight.sh
```

PyYAML 이 없으면 `ci-runs-preflight` 게이트는 **실패로 닫힌다**. 못 읽은 워크플로우를
읽은 것으로 치지 않기 위해서다. 그 외 의존성은 없다(파이썬 3.9+ · git · bash).

이것이 진입점이다. 이 저장소의 **모든** 게이트를 돌리고, **CI 도 같은 스크립트를 부른다** —
게이트 목록을 따로 갖고 있지 않다. 여기서 초록이면 파이프라인도 초록이고, 빨간불이면 push 하지 않는다.

한 번 설치해 두면 잊을 수 없다:

```bash
bash scripts/install-hooks.sh
```

이게 있는 이유는 실제로 잊었기 때문이다. v2.7.0 은 **실패한 가드레일과 함께 배포됐다** —
push 명령이 `validate_repository.py && git commit && git push` 였고, 가드레일의 실패는
그 `&&` 사슬 밖에 있었다. 기억해서 돌려야 하는 게이트는 언젠가 안 돌아가는 게이트다.

## 게이트가 각각 답하는 질문

| | 무엇에 답하나 |
|---|---|
| `scripts/validate_repository.py` | 이 트리가 정합한가 — 매니페스트·링크·라이선스 고지·문서 |
| `scripts/harness_lint.py` | **생성된** 하네스가 팩토리가 약속한 계약을 지키는가 |
| `tests/guardrail/run_guardrail.py` | 위 둘이 **정말로** 깨진 트리를 잡는가 |

셋째가 건너뛰기 쉽고 가장 중요하다. 초록 파이프라인은 «지금 트리가 깨끗하다» 만 말하고
«게이트가 더러운 트리를 잡을 것이다» 는 말하지 않는다. 가드레일은 규칙을 하나씩 일부러
깨뜨리고, 그 규칙이 **findings 에 자기 이름을 대는 것**까지 요구한다.

나머지 절반도 돈다: **통과해야 하는** 정상 변형들. 규칙을 깨뜨려 실패를 보는 것은 그 규칙이
«발화한다» 는 것만 보여준다 — 틀린 규칙도 완벽하게 발화한다.

## 규칙을 추가할 때

1. `RULES`(harness-lint) 또는 `CHECKS`(저장소 게이트)에 넣는다.
2. `tests/guardrail/run_guardrail.py` 에 **깨뜨리는 케이스**를 넣는다. 케이스 없는 규칙이
   있으면 스위트가 아예 안 돈다 — 선택이 아니다.
3. 정상인 것을 거부할 여지가 있으면 `VALID_VARIANTS` 에도 그 모양을 넣는다.
4. 문서화한다. `lint-rule-docs` 가 구현된 모든 린트 규칙이 `skills/harness/SKILL.md` 에
   이름으로 나오고 `commands/harness-lint.md` 의 개수와 맞는지 검사한다 — 린터가 7규칙에서
   9규칙이 되는 동안 두 문서가 계속 7이라고 말했고, 그중 하나는 **플러그인 없이 쓰는
   사용자가 손으로 확인하는 목록**이었다.

## PR 체크리스트

- [ ] `bash scripts/preflight.sh` 가 초록인가
- [ ] 변경이 SKILL.md와 관련 references 간에 일관되는가 (한쪽만 고치지 않았는가)
- [ ] 트리거에 영향을 주는 description 변경이면 should-trigger / near-miss 쿼리로 검증했는가
- [ ] CHANGELOG.md에 항목을 추가했는가
- [ ] 버전 정합성: `plugin.json` = `marketplace.json` = README 뱃지 셋
      (`version-consistency` 와 `readme-parity` 가 검사한다)

## 이슈

- 버그: 재현 프롬프트 + 기대/실제 동작 + `claude --version`
- 런타임 호환성 깨짐: `compat` 라벨 — 최우선 처리
- 보안: 이슈로 올리지 말고 GitHub Private Vulnerability Reporting 을 쓴다

## 응답

1인이 여가 시간에 유지보수한다. 시간 약속은 하지 않는다 — 지킬 수 없는 약속을 물려받는 것보다
없는 편이 낫다. `compat` 라벨이 붙은 것을 먼저 본다.

## 저작권 표시

이 저장소는 [revfactory/harness](https://github.com/revfactory/harness) 의 Apache-2.0
파생본이다. 수정한 파일은 변경 고지를 달고, `docs/derived-files.json` 이 어떤 파일이
파생물인지 기록하며 `change-notice` 게이트가 그것을 강제한다. `NOTICE` 와
`docs/ATTRIBUTION.md` 참조.
