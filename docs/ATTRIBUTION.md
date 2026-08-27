<!-- Modified from revfactory/harness (Apache-2.0, Copyright 2025 robin): this
     file is new to oh-my-harness, but it documents the disposition of upstream
     work carried into this derivative. -->

# Attribution and upstream pull-request disposition

`oh-my-harness` is a derivative of [revfactory/harness](https://github.com/revfactory/harness)
by [robin (Minho Hwang)](https://github.com/revfactory), Apache-2.0, Copyright 2025 robin.

This page records where the content came from, so credit is traceable rather than implied.

## Baseline

The starting tree is **not** upstream `main`. Upstream `main` is still v1.2.0, which builds
its default execution mode on `TeamCreate` / `TeamDelete` — APIs Claude Code removed in
2.1.178. Because the harness is plain Markdown, a missing tool does not raise an error; the
model improvises, so a v1 harness silently stops doing what its own docs describe.

Upstream fixed this in a v2 rebuild that has never been merged:

| Source | Author | What it is |
|---|---|---|
| [PR #51](https://github.com/revfactory/harness/pull/51) | robin ([@revfactory](https://github.com/revfactory)) | The v2.1.0 ground-up rebuild. Blocked since 2026-07-20 by a merge conflict on a head branch with `maintainerCanModify=false`, so nobody else could unblock it in place. |
| [PR #56](https://github.com/revfactory/harness/pull/56) | Rudlord Rud ([@chipoto69](https://github.com/chipoto69)) | Reconciles PR #51 against upstream `main`; `MERGEABLE`. This is the exact tree this repository starts from. |

The first commit in this repository is that tree, unmodified, so `git log` shows the
provenance rather than burying it in a notice file.

## How pull requests were judged

Every open pull request on upstream at the time of the fork was read and given one of three
dispositions. The rule applied throughout: **adopt what we can verify and are willing to
maintain.** A reference document we cannot test is a rule copy that rots, and a stale rule
copy is worse than a missing one.

- **ADOPTED** — carried into this repository, adapted to the v2 structure where needed
- **SUPERSEDED** — the v2 rebuild already solves the same problem; the named file replaces it
- **REJECTED** — not carried, with the reason classed as *out of scope*, *regression*, or *quality*

## Disposition — 24 open pull requests

| PR | Title | Author | Disposition | Basis |
|---|---|---|---|---|
| [#56](https://github.com/revfactory/harness/pull/56) | fix: resolve release v2.1.0 merge conflict | [@chipoto69](https://github.com/chipoto69) | ADOPTED | This is the baseline tree. Also contributed `scripts/validate_repository.py` and the JSON / conflict-marker workflow. |
| [#55](https://github.com/revfactory/harness/pull/55) | ci: add harness validation gate | [@chipoto69](https://github.com/chipoto69) | ADOPTED | First real CI on the project. Kept and extended: broken links promoted from warning to error, four gates added, and a guardrail suite that proves each gate fails. |
| [#54](https://github.com/revfactory/harness/pull/54) | fix: broken star history chart | [@OctoBored](https://github.com/OctoBored) | REJECTED — out of scope | The premise does not hold here: `api.star-history.com` returns 200 on check. Our chart block was already retargeted to this repository, and moving image loads to an unofficial mirror is not a trade we want. |
| [#51](https://github.com/revfactory/harness/pull/51) | feat!: 하네스 v2 전면 재구축 및 v2.1.0 릴리스 | [@revfactory](https://github.com/revfactory) | ADOPTED | The entire v2 substance of this repository. See Baseline above. |
| [#49](https://github.com/revfactory/harness/pull/49) | [codex] add codex plugin port | [@sleepylion99](https://github.com/sleepylion99) | REJECTED — out of scope | Duplicates `SKILL.md` plus six reference files under `plugins/harness-codex/`. Two copies of the same rules diverge; the copy is the one nobody updates. A Codex port belongs in its own repository. |
| [#46](https://github.com/revfactory/harness/pull/46) | fix(docs): correct plugin install command | [@k002bill2](https://github.com/k002bill2) | ADOPTED | Still valid against v2: `docs/quickstart.md` continued to tell users to install `harness@harness`, which does not resolve. Applied with this repository's plugin id. |
| [#45](https://github.com/revfactory/harness/pull/45) | feat: add opt-in evidence-driven self-evolution loop to Phase 7 | [@epoko77-ai](https://github.com/epoko77-ai) | ADOPTED | v2's `skills/evolve/SKILL.md` covers only feedback-driven evolution; it has no held-out non-regression gate. This adds the one thing the factory was missing — a way to tell whether an added agent actually helped, and to drop it when it did not. |
| [#44](https://github.com/revfactory/harness/pull/44) | fix: Phase 0 consistency, incremental QA, and user handoff | [@mythkiven](https://github.com/mythkiven) | SUPERSEDED | The Phase 0 numbering fix is already in `skills/harness/SKILL.md` (Phase 5-5 and the output checklist both say Phase 0). The other two proposals are the same as PR #6, which came first and is credited there. |
| [#43](https://github.com/revfactory/harness/pull/43) | docs: add Cursor runtime port guide | [@mythkiven](https://github.com/mythkiven) | REJECTED — regression | `docs/cursor-port.md` presents `TeamCreate` / `TeamDelete` / `TaskCreate` as the current Claude Code API and tells readers `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` "applies to Claude Code only". Those were removed in 2.1.178. Shipping it would reintroduce the exact defect this fork exists to fix. |
| [#42](https://github.com/revfactory/harness/pull/42) | docs: add Simplified Chinese localization and skill triggers | [@mythkiven](https://github.com/mythkiven) | REJECTED — regression | `README_ZH.md` translates the v1 body. Merging it would resurrect the removed `TeamCreate` guidance in Chinese, in a language we cannot keep current. |
| [#41](https://github.com/revfactory/harness/pull/41) | chore: add validate_skills script and lint CI workflow | [@mythkiven](https://github.com/mythkiven) | ADOPTED (partial) | Its frontmatter and reference checks are already covered by `scripts/validate_repository.py`, but its **size budget** for `SKILL.md` and reference files is unique and worth keeping — context efficiency is the product here. The scoped `markdownlint` step is not adopted: upstream's own PR #55 verified it fails on pre-existing Markdown debt. |
| [#40](https://github.com/revfactory/harness/pull/40) | feat: allow per-task model tiering instead of forcing opus | [@mythkiven](https://github.com/mythkiven) | SUPERSEDED | `skills/harness/references/model-selection-guide.md` (v2.1.0) replaces the blanket `model: "opus"` pin with a per-agent tier decision. |
| [#39](https://github.com/revfactory/harness/pull/39) | docs: add multi-source news intelligence team example | [@mythkiven](https://github.com/mythkiven) | REJECTED — regression | The example orchestrates with `TeamCreate(validation-team)`. Adopting it would reintroduce the removed API as an instruction, which is the exact defect this fork exists to fix. The accompanying third-party promotion row is separately out of scope. |
| [#38](https://github.com/revfactory/harness/pull/38) | feat: add output locale selection in Phase 1 | [@mythkiven](https://github.com/mythkiven) | ADOPTED | v2 has no locale handling at all. Generated agents and skills defaulted to the meta-skill's own language regardless of who was asking. |
| [#30](https://github.com/revfactory/harness/pull/30) | Add Kiro-native harness port | [@leehj2-markany](https://github.com/leehj2-markany) | REJECTED — out of scope | Same reasoning as PR #49: a second runtime's copy of the rules under `.kiro/` that would drift from the source. |
| [#27](https://github.com/revfactory/harness/pull/27) | Add harness runner, repo-specific agents, logging, and defaults | [@goccafechat](https://github.com/goccafechat) | REJECTED — quality | Four `__pycache__/*.pyc` files are committed. Beyond that, it introduces a Python runtime and changes what the project is: an instruction factory becomes an application. |
| [#23](https://github.com/revfactory/harness/pull/23) | feat(skill): add Chinese trigger phrases to the harness skill | [@hyhmrright](https://github.com/hyhmrright) | ADOPTED | Distinct from PR #22: it only widens trigger matching in the `description` fields — `plugin.json`, `marketplace.json`, and `skills/harness/SKILL.md`. Version-independent, and it cannot go stale the way a translated body can. |
| [#22](https://github.com/revfactory/harness/pull/22) | docs: add Chinese (Simplified) translation | [@hyhmrright](https://github.com/hyhmrright) | REJECTED — regression | Same reason as PR #42 — a translation of the v1 body. |
| [#21](https://github.com/revfactory/harness/pull/21) | docs: add Hermes system design maps | [@chipoto69](https://github.com/chipoto69) | REJECTED — out of scope | Hermes is a third-party system; the document itself opens with "adapter plan, not current Harness runtime behavior". |
| [#13](https://github.com/revfactory/harness/pull/13) | feat(harness): Hook 통합 — Memo 패턴 자동화 (선택) | [@namojo](https://github.com/namojo) | REJECTED — out of scope | Guides users to patch their global `settings.json`. A derivative telling people to edit their own hook configuration is a risk we are not taking on, and it depends on PR #11, which is also not adopted. |
| [#12](https://github.com/revfactory/harness/pull/12) | feat(harness): 검색 효율화 — Grep/Read 4-Step 탐색 프로토콜 (선택) | [@namojo](https://github.com/namojo) | ADOPTED | Nothing in v2 addresses search-token blowup in generated agents, the guidance is runtime-agnostic, and it is testable by reading it. Kept opt-in as the author intended. |
| [#11](https://github.com/revfactory/harness/pull/11) | feat(harness): Memo 패턴 — 분산 슬롯 + 공유 헤더 (선택) | [@namojo](https://github.com/namojo) | REJECTED — out of scope | Designed before the Workflow tool existed. v2 covers durable state with `_workspace/` and workflow `resumeFromRunId`; a second, parallel persistence convention would compete with it. |
| [#10](https://github.com/revfactory/harness/pull/10) | feat(harness): add interview-driven HRD workflow and HITL architecture review gates | [@leebaro](https://github.com/leebaro) | REJECTED — out of scope | The HITL review gate is the appealing half, but it is wired into a six-state HRD detection rewrite of Phase 0 that cannot be separated cleanly from the v2 phase structure. |
| [#6](https://github.com/revfactory/harness/pull/6) | fix: Phase 번호 일관성·Incremental QA 훅·사용자 핸드오프 3건 | [@gd452](https://github.com/gd452) | ADOPTED (partial) | The Phase-numbering third is already fixed in v2. The other two are not: v2 has no incremental-QA rule and no user-handoff step, so a user who just had a harness built is not told how to invoke it. Both adopted, adapted to v2's execution-mode names. |

## One upstream decision deliberately reversed

Upstream's v2 changelog records dropping the Japanese README with a stated reason:
*"README_JA — maintenance cost versus low utility. Keeping EN/KO only."* That reason was
sound, and this repository reverses it, so it owes an explanation.

The objection to a translation is not the translation — it is that nobody can tell when it
has gone stale. Rejecting PRs #22 and #42 (Chinese) for exactly that reason while quietly
adding Japanese would have been inconsistent. So the drift was made **detectable** instead:
the `readme-parity` gate requires every `README_*.md` to carry the same version badge and
the same number of top-level sections as `README.md`, and CI fails when they diverge.

That gate immediately found pre-existing drift — the Korean README had been missing two
sections since upstream — which is the point. A translation is maintainable when its
staleness is a build failure rather than something a reader notices first.

The same gate is what would make a future Chinese README viable. PRs #22 and #42 remain
rejected because they translate the **v1** body, not because the language is unwelcome.

## Contributors whose work is included

Beyond the baseline authors, this repository carries adopted work from:

- [@gd452](https://github.com/gd452) — incremental QA rule, user handoff step (PR #6)
- [@namojo](https://github.com/namojo) — Grep/Read 4-step search protocol (PR #12)
- [@hyhmrright](https://github.com/hyhmrright) — Chinese trigger phrases (PR #23)
- [@mythkiven](https://github.com/mythkiven) — output locale selection (PR #38), skill size budget (PR #41)
- [@epoko77-ai](https://github.com/epoko77-ai) — evidence-driven self-evolution loop (PR #45)
- [@k002bill2](https://github.com/k002bill2) — plugin install command fix (PR #46)
- [@chipoto69](https://github.com/chipoto69) — CI validation gate (PR #55), v2.1.0 conflict resolution (PR #56)
- [@revfactory](https://github.com/revfactory) — the v2 rebuild itself (PR #51) and the original project

If your work is listed here and you would like the credit worded differently, or removed,
open an issue and it will be changed.

## Relationship to upstream

This is a fork by circumstance, not by disagreement. Upstream's v2 design is sound, and
its own README is careful enough to label the project's A/B numbers as author-measured and
tell readers to run their own pilot. What stalled was merging, not thinking. If upstream
resumes, work here is offered back — the disposition table above is written so any of it
can be lifted out and turned into a pull request.
