<!-- Modified from revfactory/harness (Apache-2.0, Copyright 2025 robin).
     Releases 2.1.0 and earlier are upstream's; 2.2.0 is this derivative's. -->

# Changelog

이 프로젝트는 [Semantic Versioning](https://semver.org/)을 따릅니다.

`oh-my-harness` 는 [revfactory/harness](https://github.com/revfactory/harness) 의 파생본입니다.
**2.1.0 이하 항목은 업스트림의 기록**이며, 2.2.0 부터가 이 저장소의 변경입니다.
채택·기각한 업스트림 PR 의 전수 판정은 [docs/ATTRIBUTION.md](docs/ATTRIBUTION.md) 에 있습니다.

## [2.3.1] - 2026-08-27

정확성 릴리스. 2.3.0 에서 낸 린터가 **자기 규칙을 스스로 어겼다.**

### Fixed

- 🔴 **린터가 우리가 시킨 대로 만든 하네스를 거부했다** — Phase 1-7 은 "생성물은 사용자 locale 을
  따른다"고 지시하는데, `agent-sections` 는 한국어·영어 제목만 찾았다. 일본어로 생성하면
  우리 린터가 우리 지시를 위반했다고 판정했다. 언어별 제목 매칭을 버리고 **구조(섹션 4개)** 를 센다
- **`agent-frontmatter` 가 `name`≠파일명을 실패시켰다** — 해석은 `name` 기준이라 둘이 달라도
  합법이다. 게다가 에러 메시지가 「닿지 못한다」고 **사실이 아닌 근거**를 댔다. 규칙 제거
- **`orphan-agents`·`user-scope-shadowing` 이 에이전트를 파일명으로 식별했다** — 같은 가정이
  다른 규칙에 복제돼 있었다. 이름 해석을 `Harness.agent_name()` 한 곳으로 통일
- **`model-tiering` 이 「전원 같은 티어」를 결함으로 봤다** — 같은 성질의 업무라면 같은 티어가
  정답일 수 있다. 실제 v1 안티패턴인 **전원 `opus` 고정**만 잡도록 좁혔다
- **스킬 탐색이 재귀가 아니었다** — 중첩 스킬을 놓쳤다. `rglob`
- README 3종·SKILL.md 에 적혀 있던 위 틀린 근거 12곳 교정

### Added

- **가드레일에 «유효 변형은 PASS 해야 한다» 단계** — 지금까지는 규칙을 깨뜨려 FAIL 하는 것만
  증명했다. 그건 규칙이 **발화한다**는 증거일 뿐 **옳다**는 증거가 아니다. 잘못된 규칙도 완벽하게
  FAIL 한다. 일본어 하네스 · `name`≠파일명 · 전원 sonnet 세 변형이 통과해야 한다.
  이 단계는 도입 즉시 `orphan-agents` 의 남은 결함을 잡아냈다

---

## [2.3.0] - 2026-08-27

이 릴리스의 한 줄: **팩토리가 «규칙을 쓰는 것»에서 «규칙이 지켜졌는지 검사하는 것»으로 넘어갔다.**
규칙을 생성하고 아무도 검사하지 않는 것이 이 도메인의 측정된 실패 모드다.

### Added

- **`scripts/harness_lint.py` — 생성된 하네스를 계약에 대고 검사하는 린터.** 대상 프로젝트의
  `.claude/agents/` 와 `.claude/skills/` 를 읽어 결정적 규칙 7종을 돌린다:
  `agent-frontmatter` · `agent-sections` · `dead-api` · `user-scope-shadowing` ·
  `skill-frontmatter` · `orphan-agents` · `model-tiering`.
  전부 **셀 수 있는** 규칙이다 — 문체·품질을 점수 매기지 않는다. 논쟁하는 검사는 꺼지고,
  꺼진 검사는 커버리지처럼 보여서 없는 것보다 나쁘다
- **`orphan-agents`** — 아무 오케스트레이터도 안 부르는 에이전트, 그리고 정의 없는 에이전트 호출.
  「에이전트 27개를 만들었는데 그중 몇 개가 실제로 도나」에 처음으로 답하는 규칙
- **`commands/` 3종** — `/oh-my-harness:harness-lint` · `harness-audit` · `harness-evolve`
- **`hooks/` — SessionStart v1 잔재 감지기.** 프로젝트가 제거된 API 를 «지시»하면 세션 시작에
  1회 경고. `.claude/agents/` 가 없으면 쳐다보지도 않고, 설명문(「제거됐다」)에는 침묵한다
- **에이전트 프론트매터 풀 스펙** — `disallowedTools` `effort` `maxTurns` `isolation: worktree`
  `memory` `skills` `background` `color` 와 «언제 쓰나» 표.
  🔴 **플러그인 배포 에이전트는 `hooks`·`mcpServers`·`permissionMode` 를 무시한다**는 함정도 명시
- **`tests/fixtures/clean-harness/`** — 린터의 기준점이 되는 «올바른» 생성 하네스 샘플
- 가드레일 확장: 저장소 검사 10종 + **harness-lint 규칙 7종**, 총 17개 게이트가 각각
  깨진 입력에서 실제로 발화함을 증명

### Changed

- **Phase 6-1 이 산문 체크리스트에서 명령 한 줄로 바뀌었다** — 「확인했다」가 아니라
  `harness_lint.py` 의 출력과 exit code 가 근거다
- `marketplace.json` 에 description 추가 (`claude plugin validate` 경고 해소)
- 저장소 스캔에서 `tests/` 전체 제외 — 일부러 깨뜨린 픽스처가 본검사를 깨지 않도록

---

## [2.2.0] - 2026-08-27

첫 파생 릴리스. 업스트림의 미머지 v2.1.0(PR #51 → 충돌해소본 #56)을 베이스로 삼고,
열린 PR 24건을 전수 판정해 채택분을 반영하고, 검사기 자체를 검증하는 CI 를 세웠다.

### Added

- **`docs/ATTRIBUTION.md`** — 업스트림 열린 PR 24건 전수 판정표(ADOPTED 10 / SUPERSEDED 2 / REJECTED 12)와 기여자 크레딧
- **`NOTICE`** — Apache-2.0 §4 귀속 고지, PR #51/#56 계보
- **`README_JA.md`** — 일본어 README 를 v2 기준으로 재작성. ⚠️ 업스트림 v2 는 **의도적으로** 이걸 뺐다("유지보수 부담 대비 효용 저조, EN/KO 2종 유지"). 그 판단이 옳았기에 되돌리는 대신 **드리프트를 탐지 가능하게** 만들었다 — `readme-parity` 검사 참조. 근거는 [docs/ATTRIBUTION.md](docs/ATTRIBUTION.md) 「One upstream decision deliberately reversed」
- **Phase 1-7 출력 locale 결정** — 생성물 본문 언어가 사용자 locale 을 따르도록. `_workspace/00_locale.md` 기록 (upstream PR #38, [@mythkiven](https://github.com/mythkiven))
- **Phase 6-7 사용자 핸드오프** — 구축 직후 트리거 예문·skill name·산출물 경로 안내 (upstream PR #6, [@gd452](https://github.com/gd452))
- **`references/self-evolution-loop.md` + Phase 7 포인터** — 증거 주도 자율 진화 루프(옵트인). 자격 게이트 A/B/C, 실패 시그니처 `(c, q, m)`, held-in/held-out 비퇴행 수용 규칙 (upstream PR #45, [@epoko77-ai](https://github.com/epoko77-ai))
- **`references/search-efficiency.md` + Phase 1-8 포인터** — Grep/Read 4-Step 탐색 프로토콜(선택) (upstream PR #12, [@namojo](https://github.com/namojo))
- **`orchestrator-template.md` Incremental QA 공통 규칙** — QA 를 마지막 단계에만 두지 않도록 전 템플릿에 검증 훅 (upstream PR #6, [@gd452](https://github.com/gd452))
- **description 중국어 트리거** — 트리거 매칭 확장 (upstream PR #23, [@hyhmrright](https://github.com/hyhmrright))
- **CI 검사 4종 신설** — `link-existence` · `dead-api` · `version-consistency` · `change-notice`
- **`size-budget` 검사** — SKILL.md 520줄 / reference 650줄 예산 (upstream PR #41, [@mythkiven](https://github.com/mythkiven))
- **`readme-parity` 검사** — 모든 `README_*.md` 가 `README.md` 와 같은 버전 뱃지·같은 최상위 섹션 수를 갖는지. 번역본의 드리프트를 «빌드 실패»로 만든다
- **`tests/guardrail/`** — 검사기 9종 각각을 일부러 깨뜨려 «실제로 FAIL 하는지» 증명하는 스위트. CI 별도 잡으로 상시 실행

### Changed

- **한국어·일본어 README 에 누락 섹션 2개 보강** — `Category` 와 `Star History`. 한국어판은 업스트림 시절부터 빠져 있었고 `readme-parity` 신설로 발견됐다
- **`oh-my-harness` 로 리브랜드** — 플러그인·마켓플레이스 이름, 저자, 저장소 URL. **스킬 이름 `harness`·`evolve` 는 유지** (트리거 문구와 v1 마이그레이션 경로 보존)
- **깨진 로컬 링크를 경고에서 에러로 승격** — 초록불 옆의 경고는 «괜찮음»으로 읽힌다. 실재하지 않는 문서 4개가 업스트림에서 몇 달간 참조된 원인
- **Phase 0 / Phase 3-0 중복 검토가 유저 스코프까지 감사** — `~/.claude/agents/` 를 함께 읽는다. 프로젝트 스코프가 유저 스코프를 덮으므로, 같은 이름을 만들면 사용자의 전역 에이전트가 경고 없이 사라진다
- **워크플로우 통합** — `harness-validation.yml` 을 `validation.yml` 로 합침

### Security

- 🔴 **이슈 템플릿이 보안 신고를 제3자에게 보내고 있었다** — 업스트림에서 그대로 상속한 `.github/ISSUE_TEMPLATE/config.yml` 이 비공개 취약점 제보를 **원저자의 회사 이메일**로 보내고, `bug_report.yml` 이 이슈를 `revfactory` 에게 자동 할당했다. 원저자는 이 파생본의 제보를 받기로 한 적이 없다. 전 경로를 이 저장소로 재배선했고 보안 채널은 GitHub Private Vulnerability Reporting 으로 교체
- **이슈 템플릿의 재현 절차가 삭제된 API 를 지시하고 있었다** — `export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` 와 존재하지 않는 `harness@harness` 설치 명령. `dead-api` 가 마크다운만 스캔해서 `.yml` 을 통과시켰다 → 검사를 `.yml`/`.yaml` 로 확장하고 YAML 가드레일 픽스처 추가

### Fixed

- **LICENSE 를 Apache 공식 원문으로 복원** — 상속본이 라이선스 **본문 3곳**을 바꿔놨다(`submitted to Licensor`→`the Licensor`, `received by Licensor`→`the Licensor`, `excluding those notices`→`any notices`)+부록 삭제. 본문이 바뀐 라이선스는 Apache License 라 보기 어렵다. 원저자 저작권은 NOTICE 와 각 파일 고지에 보존
- **JSON 두 개가 스스로 변경 고지를 지니게** — `_notice` 키. Apache-2.0 §4(b) 는 "수정된 파일이 고지를 carry" 하라고 하지 JSON 예외를 두지 않는다. NOTICE 대체 주장에 기대지 않는다
- **`/harness:evolve` → `/oh-my-harness:evolve`** — 리브랜드 후 플러그인 스킬 호출은 `plugin-name:skill-name` 이라 기존 표기가 존재하지 않는 명령이 됐다
- **PR #23 채택 주장을 사실로** — 중국어 트리거를 두 매니페스트에만 넣고 `skills/harness/SKILL.md` description 을 빠뜨려, ATTRIBUTION 의 ADOPTED 가 절반만 참이었다

- **`docs/quickstart.md` 설치 명령** — 존재하지 않는 `harness@harness` 를 안내하고 있었다 (upstream PR #46, [@k002bill2](https://github.com/k002bill2))
- **충돌마커 검사의 거짓양성** — `=======` 는 마크다운 setext 제목 밑줄과 같다. 같은 파일에 여는/닫는 마커가 있을 때만 중간 마커로 판정하도록 수정
- **`dead-api` 검사의 거짓양성** — 마이그레이션 가이드·체인지로그는 제거된 API 를 «설명»해야 한다. 파일 단위 예외 + 부정어 확장으로 거짓양성 0

### Removed

- **`[Unreleased]` 섹션의 v1 잔재** — v2 가 삭제한 `references/agent-design-patterns.md` 를 가리키고 있었다

---

## [2.1.0] - 2026-07-20

### Changed

- **모델 정책 개편: "세션 모델 상속 기본" → "업무 특성 기반 티어 선택"** — 에이전트 정의 시 업무의 복잡도·작업 기간·자율성·응답 속도 4가지 기준으로 opus(설계·코드 생성·복잡한 분석·교차 검증, 계획·장기 자율 실행) / sonnet(로그 파싱·포맷 변환·단순 수집 등 일상·기계적 업무)을 에이전트별로 선택하도록 변경. 애매하면 sonnet, 무근거 일괄 지정 금지 원칙 유지
- **버전 정합성 2.1.0 동기화** — `.claude-plugin/plugin.json`·`marketplace.json`·README 뱃지(EN/KO)를 2.1.0으로 통일

### Added

- **`references/model-selection-guide.md`** — 티어별 핵심 역할·적합 업무·선택 상황, Opus vs Sonnet 구분 기준, 하네스 적용 규칙(업무 단위 판단, 계층 분리, 워크플로우 단계별 적용) 상세 가이드

## [2.0.0] - 2026-07-19

전면 재구축 (ground-up rebuild). v1의 전제였던 실험적 Agent Teams API가 현행 Claude Code에서 사라졌고, 결정적 오케스트레이션을 위한 Workflow 도구가 새로 추가된 환경 변화에 맞춰 모든 것을 다시 설계했다.

### Breaking / Fixed

- **`TeamCreate`/`TeamDelete`/`team_name` 전면 제거** — 현행 런타임에 존재하지 않는 API. 세션의 단일 암묵 팀 + `Agent(name:)` + `SendMessage` 구조로 전 템플릿 재작성. v1 오케스트레이터는 이 API를 호출하다 단일 에이전트 실행으로 조용히 퇴화하는 실질적 브로큰 상태였다
- **`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` 의존 제거** — 플래그 안내 문서(`docs/experimental-dependency.md`) 및 모든 참조 삭제. v2는 플래그 없이 동작한다
- **`model: "opus"` 전 에이전트 강제 정책 폐기** — 세션 모델 상속이 기본. 오버라이드는 근거(기계적 작업의 비용 절감 / 최고 난도 검증)가 있을 때만 명시
- **README-실체 불일치 해소** — v1 README가 홍보하던 `/harness:evolve` 스킬이 실제로는 존재하지 않았다. v2에서 실제 스킬로 출시
- **"세션당 한 팀" 제약 및 팀 재구성 절차 삭제** — 제약 자체가 소멸

### Added

- **3중 실행 모드 체계** — 워크플로우 오케스트레이션(신규) / 퍼시스턴트 에이전트 협업(v1 팀 모드 대체) / 서브에이전트 위임. 모드 선택 기준을 "팀 크기"에서 **"제어 흐름의 결정성"**으로 재정의
- **워크플로우 오케스트레이션 모드** — `Workflow` 도구 기반: `pipeline()`/`parallel()`, 구조화 출력 스키마(파싱 불필요), `budget` 연동 규모 조절, `resumeFromRunId` 부분 재실행, 커스텀 `agentType`, `isolation: worktree`
- **품질 패턴 카탈로그** — 적대적 검증, 관점 분산 검증, 심판 패널, loop-until-dry, 다각 스윕, 완전성 비평가, 침묵 상한 금지
- **`skills/evolve` (`/harness:evolve`)** — 델타 수집 → 피드백 유형 분류 → 일반화 반영 → 변경 이력 갱신 → 진화 보고의 5단계 진화 스킬. 관찰 기반 진화 신호(반복 피드백, 오케스트레이터 우회 흔적) 감지 포함
- **v1 → v2 마이그레이션 경로** — Phase 0에서 v1 산출물 자동 감지, `docs/migration-v1-to-v2.md` + `references/execution-modes.md`에 변환 매핑 표
- **신규 레퍼런스** — `execution-modes.md`(3중 모드 + 마이그레이션), `workflow-recipes.md`(스크립트 스켈레톤 6종 + 함정 12종 체크리스트)
- **데이터 전달 프로토콜에 "구조화 반환" 추가** — 워크플로우 schema 기반 타입 안전 전달을 v2 권장 기본으로
- **워크플로우 기반 A/B 테스트** — 스킬 검증(with/without)을 워크플로우 스크립트로 구성하는 레시피
- **에이전트 정의 확장** — 프론트매터 `tools`(읽기 전용 리뷰어 등 도구 제한), `재호출 지침` 섹션 표준화

### Changed

- **6패턴 각각에 v2 권장 실행 모드 매핑** — 팬아웃/파이프라인은 워크플로우 1순위, 감독자는 퍼시스턴트+태스크, 계층 위임은 워크플로우 1단계 중첩 등
- **오케스트레이터 템플릿 3종 전면 재작성** — A: 워크플로우(정찰→실행→종합, run_meta/resume 포함), B: 퍼시스턴트(스폰+태스크+피드백 루프), C: 서브에이전트
- **Phase 7 재구성** — 운영/유지보수는 harness 스킬에 유지, 진화(피드백 반영)는 evolve 스킬로 분리
- 산출물 체크리스트에 v1 잔재 검증·워크플로우 함정 검증 항목 추가
- `references/agent-design-patterns.md` → `team-patterns.md`로 개편 (품질 패턴 흡수), `team-examples.md` 5종 예시를 v2 문법으로 재작성

### Removed

- **마케팅/사이트 자산 제거** — `harness_banner.png`·`harness_icon.png`·`harness_social.png`·`harness_team.png`(합계 약 9MB), `index.html`(랜딩 페이지), `privacy.html`
- **저장소 운영 부산물 제거** — 런치 캠페인용 `_workspace/` 산출물, 마케팅 에이전트 정의(`.claude/agents/launch-strategist` 등), `docs/experimental-dependency.md`
- README_JA (일본어 README) — 유지보수 부담 대비 효용 저조. EN/KO 2종 유지

## [1.2.1] - 2026-04-18

### Fixed

- **버전 정합성 동기화** — README.md / README_KO.md / README_JA.md 뱃지가 `v1.0.1`, `.claude-plugin/marketplace.json`이 `1.1.0`, `.claude-plugin/plugin.json`이 `1.2.0`으로 3중 불일치 → 모두 **v1.2.0**으로 통일 (plugin.json 기준)
- **태그드 릴리스 0건 상태 해소 준비** — v1.0.0 / v1.0.1 / v1.1.0 / v1.2.0 소급 태그 계획 작성 (`_workspace/release/audit-2026-04-18.md` §4 참조)

### Added

- **포지셔닝 선언: "harness factory"** — README 상단에 카테고리 자기 규정 문구를 도입. "에이전트 + 스킬을 도메인별로 찍어내는 하네스 팩토리"로 카테고리 선점 (단일 에이전트/프롬프트 프레임워크 대비 차별화)
- **CONTRIBUTING.md** — 기여 가이드 및 SLA 명시 (PR 1차 응답 72h, Issue triage 48h). 커뮤니티 온보딩 장벽 해소
- **docs/ 디렉토리** — 장기 문서(아키텍처, 마이그레이션, 패턴 카탈로그) 이전 공간 신설. README 비대화 방지 및 검색성 향상
- **Issue #3 응답 정책** — 커뮤니티 이슈에 대한 공식 응답 템플릿 및 트리아지 프로세스 추가

### Changed

- `.claude-plugin/marketplace.json` version: `1.1.0` → `1.2.0`
- README 뱃지 (EN/KO/JA 3종): `Version-1.0.1` → `Version-1.2.0`
- **`.claude-plugin/plugin.json` description 재작성** — `"Agent Team & Skill Architect — Meta-skill that designs..."` → `"The team-architecture factory for Claude Code — a meta-skill that turns a domain description into an agent team and the skills they use, with six pre-defined team-architecture patterns..."` (EN+KO 병기, L3 Meta-Factory 포지셔닝 반영)
- **`.claude-plugin/plugin.json` keywords 확장** — 5개 → 17개 (`harness-factory`, `team-architecture-factory`, `claude-code-plugin`, `agent-scaffolding`, `multi-agent`, 6패턴 키워드 6종 추가)

## [1.2.0] - 2026-04-08

### Changed

- **CLAUDE.md 등록 정책 간소화 (중복 제거)** — Phase 5-4 "컨텍스트 등록"을 "포인터 등록"으로 전환. 에이전트 목록·스킬 목록·디렉토리 구조·실행 규칙 상세를 CLAUDE.md에서 제거하고 **트리거 규칙 + 변경 이력**만 남김. 에이전트/스킬 목록은 `.claude/agents/`, `.claude/skills/` 및 오케스트레이터 스킬에서 단일 출처로 관리
- **Phase 3/4 임시 동기화 단계 삭제** — CLAUDE.md 동기화 부담을 줄이기 위해 Phase 3/4의 임시 동기화 지시 제거. 최종 포인터 등록은 Phase 5-4에서 1회만 수행
- **핵심 원칙 3번 재정의** — "CLAUDE.md에 하네스 컨텍스트를 등록한다" → "CLAUDE.md에 하네스 포인터를 등록한다"
- **CLAUDE.md vs 오케스트레이터 역할 분담표 삭제** — 포인터 정책으로 단순화되어 표 자체가 불필요해짐

### Added

- **Phase 2-1: 하이브리드 실행 모드** — 에이전트 팀 / 서브 에이전트에 더해 Phase별로 모드를 섞는 하이브리드 패턴 추가. 자주 쓰이는 조합(병렬 수집→합의 통합, 팀 생성→검증, Phase 간 팀 재구성) 명시
- **Phase 2-1 실행 모드 비교표** — 팀/서브/하이브리드 3종 특성 및 의사결정 순서 3단계 제공
- **Phase 5-0 하이브리드 오케스트레이터 패턴** — 하이브리드 구성 시 각 Phase 상단에 실행 모드를 명시하는 규칙
- **Phase 5-1 반환값 기반 데이터 전달** — 서브 에이전트 모드 전용 데이터 전달 전략 추가 (기존 메시지/태스크/파일 + 반환값)
- **Phase 5-1 권장 조합 (서브/하이브리드)** — 팀 모드 외 서브 모드와 하이브리드에서의 데이터 전달 권장 조합 명시

## [1.1.0] - 2026-04-05

### Added

- **Phase 0: 현황 감사** — 트리거 시 기존 하네스 상태를 먼저 확인하고 신규 구축/기존 확장/운영·유지보수 3분기로 라우팅
- **기존 확장 Phase 선택 매트릭스** — 에이전트 추가/스킬 추가/아키텍처 변경별 필요 Phase를 명시한 결정표
- **Phase 3/4 CLAUDE.md 임시 동기화** — 에이전트·스킬 생성 직후 CLAUDE.md에 즉시 반영 (세션 중단 내성)
- **Phase 5-4: CLAUDE.md 하네스 컨텍스트 등록** — 에이전트 팀 구조·스킬 목록·실행 규칙·디렉토리 구조·변경 이력을 기록. CLAUDE.md vs 오케스트레이터 역할 분담표 포함
- **Phase 5-5: 후속 작업 지원** — 오케스트레이터 description에 후속 키워드 필수 포함, Phase 0 컨텍스트 확인 단계로 초기/부분재실행/새실행 자동 판별
- **Phase 5 오케스트레이터 수정 경로** — 기존 확장 시 오케스트레이터를 새로 만들지 않고 수정하는 가이드
- **Phase 7: 하네스 진화 메커니즘** — 실행 후 피드백 수집 → 피드백 유형별 수정 대상 매핑 → 변경 이력 기록 → 자동 진화 트리거
- **Phase 7-5: 운영/유지보수 워크플로우** — 현황 감사→점진적 수정→CLAUDE.md 동기화→변경 검증 4단계
- **description에 운영/유지보수 트리거** — '하네스 점검', '하네스 감사', '하네스 현황', '에이전트/스킬 동기화' 키워드
- **산출물 체크리스트 강화** — CLAUDE.md 동기화 완료, 변경 이력 기록, Phase 0 컨텍스트 확인 항목 추가
- 오케스트레이터 템플릿에 Phase 0 (컨텍스트 확인) 추가 — 에이전트 팀/서브 에이전트 모드 모두 적용
- 오케스트레이터 description 템플릿에 후속 작업 키워드 패턴 포함

### Changed

- 핵심 원칙 2개 → 4개로 확장 (CLAUDE.md 등록, 진화 시스템 추가)
- **"진화 로그" → "변경 이력" 통일** — 이름과 스키마(4컬럼: 날짜/변경내용/대상/사유)를 전 섹션에서 일원화
- **Phase 1 Step 3** — Phase 0 감사 결과를 기반으로 충돌 분석하도록 변경 (중복 제거)
- **5-4 CLAUDE.md 템플릿 코드 블록** — 중첩 렌더링 깨짐 수정 (3백틱→4백틱)
- **역할 분담표 확장** — 스킬 목록, 디렉토리 구조, 변경 이력 행 추가
- **오케스트레이터 템플릿** — Phase 0 컨텍스트 확인 단계, 후속 작업 키워드 가이드 추가

## [1.0.1] - 2026-03-28

### Changed

- SKILL.md ↔ references 간 중복 내용 제거 (330줄 → 285줄)
  - Phase 2-1: 실행 모드 비교표/불릿 → 핵심 원칙 + agent-design-patterns.md 포인터
  - Phase 2-3: 에이전트 분리 기준 불릿 → 4축 요약 + agent-design-patterns.md 포인터
  - Phase 3: 에이전트 정의 템플릿 코드블록 → 필수 섹션 나열 + references 포인터
  - Phase 5-2: 에러 핸들링 5행 테이블 → 핵심 원칙 + orchestrator-template.md 포인터

## [1.0.0] - 2026-03-27

### Added

- 6 Phase 워크플로우 기반 하네스 구성 메타 스킬
- 6가지 에이전트 아키텍처 패턴 (파이프라인, 팬아웃/팬인, 전문가 풀, 생성-검증, 감독자, 계층적 위임)
- 에이전트 팀 / 서브 에이전트 실행 모드 지원
- Progressive Disclosure 기반 스킬 생성 가이드
- 오케스트레이터 템플릿 (에이전트 팀 모드 + 서브 에이전트 모드)
- QA 에이전트 통합 가이드 (실제 프로젝트 7개 버그 사례 기반)
- 스킬 테스트/평가 방법론 (With-skill vs Without-skill 비교)
- 실전 팀 구성 예시 5종 (리서치, 소설, 웹툰, 코드리뷰, 마이그레이션)
