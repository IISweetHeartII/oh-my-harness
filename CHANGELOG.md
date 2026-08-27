<!-- Modified from revfactory/harness (Apache-2.0, Copyright 2025 robin).
     Releases 2.1.0 and earlier are upstream's; 2.2.0 is this derivative's. -->

# Changelog

이 프로젝트는 [Semantic Versioning](https://semver.org/)을 따릅니다.

`agent-foundry` 는 [revfactory/harness](https://github.com/revfactory/harness) 의 파생본입니다.
**2.1.0 이하 항목은 업스트림의 기록**이며, 2.2.0 부터가 이 저장소의 변경입니다.
채택·기각한 업스트림 PR 의 전수 판정은 [docs/ATTRIBUTION.md](docs/ATTRIBUTION.md) 에 있습니다.

## [2.2.0] - 2026-08-27

첫 파생 릴리스. 업스트림의 미머지 v2.1.0(PR #51 → 충돌해소본 #56)을 베이스로 삼고,
열린 PR 24건을 전수 판정해 채택분을 반영하고, 검사기 자체를 검증하는 CI 를 세웠다.

### Added

- **`docs/ATTRIBUTION.md`** — 업스트림 열린 PR 24건 전수 판정표(ADOPTED 10 / SUPERSEDED 2 / REJECTED 12)와 기여자 크레딧
- **`NOTICE`** — Apache-2.0 §4 귀속 고지, PR #51/#56 계보
- **`README_JA.md`** — 업스트림 PR #56 이 유실한 일본어 README 를 v2 기준으로 재작성
- **Phase 1-7 출력 locale 결정** — 생성물 본문 언어가 사용자 locale 을 따르도록. `_workspace/00_locale.md` 기록 (upstream PR #38, [@mythkiven](https://github.com/mythkiven))
- **Phase 6-7 사용자 핸드오프** — 구축 직후 트리거 예문·skill name·산출물 경로 안내 (upstream PR #6, [@gd452](https://github.com/gd452))
- **`references/self-evolution-loop.md` + Phase 7 포인터** — 증거 주도 자율 진화 루프(옵트인). 자격 게이트 A/B/C, 실패 시그니처 `(c, q, m)`, held-in/held-out 비퇴행 수용 규칙 (upstream PR #45, [@epoko77-ai](https://github.com/epoko77-ai))
- **`references/search-efficiency.md` + Phase 1-8 포인터** — Grep/Read 4-Step 탐색 프로토콜(선택) (upstream PR #12, [@namojo](https://github.com/namojo))
- **`orchestrator-template.md` Incremental QA 공통 규칙** — QA 를 마지막 단계에만 두지 않도록 전 템플릿에 검증 훅 (upstream PR #6, [@gd452](https://github.com/gd452))
- **description 중국어 트리거** — 트리거 매칭 확장 (upstream PR #23, [@hyhmrright](https://github.com/hyhmrright))
- **CI 검사 4종 신설** — `link-existence` · `dead-api` · `version-consistency` · `change-notice`
- **`size-budget` 검사** — SKILL.md 520줄 / reference 650줄 예산 (upstream PR #41, [@mythkiven](https://github.com/mythkiven))
- **`tests/guardrail/`** — 검사기 8종 각각을 일부러 깨뜨려 «실제로 FAIL 하는지» 증명하는 스위트. CI 별도 잡으로 상시 실행

### Changed

- **`agent-foundry` 로 리브랜드** — 플러그인·마켓플레이스 이름, 저자, 저장소 URL. **스킬 이름 `harness`·`evolve` 는 유지** (트리거 문구와 v1 마이그레이션 경로 보존)
- **깨진 로컬 링크를 경고에서 에러로 승격** — 초록불 옆의 경고는 «괜찮음»으로 읽힌다. 실재하지 않는 문서 4개가 업스트림에서 몇 달간 참조된 원인
- **Phase 0 / Phase 3-0 중복 검토가 유저 스코프까지 감사** — `~/.claude/agents/` 를 함께 읽는다. 프로젝트 스코프가 유저 스코프를 덮으므로, 같은 이름을 만들면 사용자의 전역 에이전트가 경고 없이 사라진다
- **워크플로우 통합** — `harness-validation.yml` 을 `validation.yml` 로 합침

### Fixed

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
