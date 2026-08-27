#!/usr/bin/env python3
"""Lint a harness this factory generated, against the contract it promised.

The factory writes rules. Rules that nothing checks are rules nobody follows —
that is the measured failure mode of this whole category, not a hypothetical
one. This script is the check.

It runs against a *target project*, not against this repository:

    python3 harness_lint.py                 # lint ./.claude
    python3 harness_lint.py path/to/project
    python3 harness_lint.py --only orphan-agents --only dead-api
    python3 harness_lint.py --list

Every rule here is countable. Nothing scores style, tone, or "quality", because
a check that argues gets switched off, and a switched-off check is worse than no
check — it looks like coverage.

Exit 0 = clean. Exit 1 = findings. Exit 2 = nothing to lint.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# The factory is told to generate in the user's locale (Phase 1-7), so matching
# section headings by their Korean or English wording would reject a harness
# built exactly as instructed in Japanese or Chinese. The contract is that four
# sections exist, not what language names them — so count structure, not words.
REQUIRED_AGENT_SECTION_COUNT = 4

# Generic role words that a global agent very often already occupies. Generating
# one of these unprefixed replaces the user's own agent inside this project, with
# no warning — project scope simply wins. The user-scope rule catches it only on
# the machine that has the collision; this one catches it everywhere.
RESERVED_GENERIC_NAMES = {
    "analyst", "architect", "builder", "critic", "debugger", "designer",
    "developer", "executor", "explore", "explorer", "planner", "researcher",
    "reviewer", "code-reviewer", "scientist", "tester", "qa", "qa-tester",
    "security-reviewer", "test-engineer", "tracer", "verifier", "writer",
    "document-specialist", "code-simplifier", "git-master",
}
HARNESS_MANIFEST = ".claude/harness.json"

# TeamCreate/TeamDelete/실험 플래그는 Claude Code 고유 식별자라 단독으로 판정해도
# 안전하다. `team_name` 은 다르다 — 스포츠·조직 관리 하네스에서 흔한 평범한 인자명이라
# 단독으로 잡으면 오진한다. 그래서 같은 줄에 Claude 문맥이 있을 때만 본다.
DEAD_API_TOKENS = ["TeamCreate", "TeamDelete", "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"]
DEAD_API_CONTEXTUAL = {"team_name": ("TeamCreate", "TeamDelete", "Agent(", "subagent_type")}
DEAD_API_NEGATIONS = [
    "removed", "remove", "no longer", "does not exist", "deprecated", "legacy",
    "gone", "dropped", "delete", "deleted",
    "제거", "없다", "없습니다", "존재하지 않", "삭제", "소멸", "금지", "잔재", "v1",
    "削除", "存在しません", "排除", "禁止", "不要",
]

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
NAME_RE = re.compile(r"^name:\s*['\"]?([A-Za-z0-9_:-]+)", re.MULTILINE)
MODEL_RE = re.compile(r"^\s*model:\s*['\"]?([A-Za-z0-9_.-]+)", re.MULTILINE)
SUBAGENT_REF_RE = re.compile(r"""subagent_type:\s*["']([A-Za-z0-9_-]+)["']|agentType:\s*["']([A-Za-z0-9_-]+)["']""")


class Finding:
    __slots__ = ("rule", "path", "line", "message")

    def __init__(self, rule: str, path: str, message: str, line: int | None = None):
        self.rule, self.path, self.line, self.message = rule, path, line, message

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"[{self.rule}] {where} — {self.message}"


class Harness:
    """The generated artefacts under a project's .claude/ directory."""

    def __init__(self, root: Path):
        self.root = root
        self.claude = root / ".claude"
        self.agents = sorted((self.claude / "agents").glob("*.md")) if (self.claude / "agents").is_dir() else []
        self.skills = sorted((self.claude / "skills").rglob("SKILL.md")) if (self.claude / "skills").is_dir() else []

    def agent_name(self, p: Path) -> str:
        """The name an agent actually resolves by.

        Resolution uses frontmatter `name`, not the filename, and the two are
        allowed to differ. Every rule that reasons about agent identity has to
        go through here — deriving it from the filename is how orphan-agents
        came to report both a phantom orphan and a phantom missing definition
        for one perfectly legal harness.
        """
        m = NAME_RE.search(frontmatter(p.read_text(encoding="utf-8")) or "")
        return m.group(1) if m else p.stem

    def rel(self, p: Path) -> str:
        try:
            return p.relative_to(self.root).as_posix()
        except ValueError:
            return p.as_posix()

    def exists(self) -> bool:
        return bool(self.agents or self.skills)


def frontmatter(text: str) -> str | None:
    m = FRONTMATTER_RE.match(text)
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

def rule_agent_frontmatter(h: Harness, out: list[Finding]) -> None:
    """name and description are present. Nothing more — see the note below."""
    for p in h.agents:
        fm = frontmatter(p.read_text(encoding="utf-8"))
        if fm is None:
            out.append(Finding("agent-frontmatter", h.rel(p), "no YAML frontmatter"))
            continue
        for field in ("name", "description"):
            # 키의 «존재» 만 보면 `description:` 뒤가 비어 있어도 통과한다. 빈 값은
            # 없는 것과 같다 — description 이 비면 위임 판정이 아예 불가능하다.
            m = re.search(rf"^{field}\s*:\s*(.*)$", fm, re.MULTILINE)
            if not m:
                out.append(Finding("agent-frontmatter", h.rel(p), f"frontmatter missing {field}:"))
            elif not m.group(1).strip().strip("\"'"):
                out.append(Finding("agent-frontmatter", h.rel(p), f"frontmatter {field}: is empty"))
        # Deliberately NOT checking that name matches the filename. Resolution
        # is by `name`, so a divergence is legal; asserting otherwise would be a
        # check that enforces a convention while stating a falsehood about why.


def rule_agent_duplicates(h: Harness, out: list[Finding]) -> None:
    """두 파일이 같은 name 을 선언하면 하나는 절대 안 불린다.

    이름 집합을 set 으로 다루면 중복이 조용히 하나로 합쳐져 어떤 규칙에도 안 걸린다.
    """
    seen: dict[str, str] = {}
    for p in h.agents:
        name = h.agent_name(p)
        if name in seen:
            out.append(Finding("agent-duplicates", h.rel(p),
                               f"declares name {name!r}, already declared by {seen[name]} — "
                               f"one of the two is unreachable"))
        else:
            seen[name] = h.rel(p)


def rule_agent_naming(h: Harness, out: list[Finding]) -> None:
    """Generated names must not squat on generic roles, and must obey the
    project's namespace when one is declared.

    Two levels, because the right strictness depends on the project:

    - Always: reject a bare generic role name. `analyst` in a project shadows
      the user's global `analyst` for everyone who has one.
    - When `.claude/harness.json` declares `agentNamespace`: require it as a
      prefix. That turns "please prefix your agents" from advice into a gate.
    """
    manifest = h.root / HARNESS_MANIFEST
    namespace = None
    if manifest.is_file():
        try:
            namespace = json.loads(manifest.read_text(encoding="utf-8")).get("agentNamespace")
        except (json.JSONDecodeError, OSError):
            out.append(Finding("agent-naming", HARNESS_MANIFEST, "is not readable JSON"))

    for p in h.agents:
        name = h.agent_name(p)
        if name in RESERVED_GENERIC_NAMES:
            out.append(Finding(
                "agent-naming", h.rel(p),
                f"{name!r} is a generic role name that global agents commonly use. "
                f"Project scope wins silently, so this replaces the user's own "
                f"{name!r} inside this project. Prefix it with the domain "
                f"(e.g. billing-{name})"))
        elif namespace and not name.startswith(f"{namespace}-"):
            out.append(Finding(
                "agent-naming", h.rel(p),
                f"{name!r} does not start with the declared namespace "
                f"{namespace!r} (see {HARNESS_MANIFEST})"))


def rule_agent_sections(h: Harness, out: list[Finding]) -> None:
    """Every agent carries the four contract sections, in whatever language."""
    for p in h.agents:
        body = p.read_text(encoding="utf-8")
        after_fm = FRONTMATTER_RE.sub("", body, count=1)
        # 코드펜스 안의 ## 은 «예시» 지 이 문서의 섹션이 아니다. 세면 본문에
        # 섹션이 하나도 없는 에이전트가 출력 예시만으로 합격한다.
        outside_fences = re.sub(r"^```.*?^```", "", after_fm, flags=re.M | re.S)
        sections = re.findall(r"^##\s+\S", outside_fences, re.MULTILINE)
        if len(sections) < REQUIRED_AGENT_SECTION_COUNT:
            out.append(Finding(
                "agent-sections", h.rel(p),
                f"{len(sections)} top-level section(s); the contract needs "
                f"{REQUIRED_AGENT_SECTION_COUNT} (role, principles, I/O protocol, collaboration) "
                f"— any language"))


def rule_dead_api(h: Harness, out: list[Finding]) -> None:
    """A removed API named as an instruction, not as history."""
    for p in h.agents + h.skills:
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            hits = [t for t in DEAD_API_TOKENS if t in line]
            hits += [t for t, ctx in DEAD_API_CONTEXTUAL.items()
                     if t in line and any(c in line for c in ctx)]
            if not hits:
                continue
            # 호출 «형태»(TeamCreate( … ))면 부정어가 같은 줄에 있어도 지시문이다.
            # "TeamCreate was removed, so call TeamCreate(x)" 한 줄로 통과하던 구멍.
            imperative = any(re.search(rf"{t}\s*\(", line) for t in DEAD_API_TOKENS)
            if not imperative and any(neg.lower() in line.lower() for neg in DEAD_API_NEGATIONS):
                continue
            out.append(Finding("dead-api", h.rel(p),
                               f"instructs {', '.join(hits)}, removed in Claude Code 2.1.178", n))


def rule_user_scope_shadowing(h: Harness, out: list[Finding]) -> None:
    """A project agent silently replaces a user's global agent of the same name.

    Project scope wins over user scope, with no warning and no error, so the
    global agent simply stops existing inside this project.
    """
    user_dir = Path(os.path.expanduser("~/.claude/agents"))
    if not user_dir.is_dir():
        return
    global_names = {h.agent_name(p) for p in user_dir.glob("*.md")}
    for p in h.agents:
        name = h.agent_name(p)
        if name in global_names:
            out.append(Finding(
                "user-scope-shadowing", h.rel(p),
                f"resolves to {name!r}, shadowing the user's global agent of that name — "
                f"prefix it (e.g. billing-{name}) or confirm the override is intended"))


def rule_skill_frontmatter(h: Harness, out: list[Finding]) -> None:
    """Skill frontmatter present, name matches its directory, references resolve."""
    for p in h.skills:
        text = p.read_text(encoding="utf-8")
        fm = frontmatter(text)
        if fm is None:
            out.append(Finding("skill-frontmatter", h.rel(p), "no YAML frontmatter"))
            continue
        for field in ("name", "description"):
            m = re.search(rf"^{field}\s*:\s*(.*)$", fm, re.MULTILINE)
            if not m:
                out.append(Finding("skill-frontmatter", h.rel(p), f"frontmatter missing {field}:"))
            elif not m.group(1).strip().strip("\"'"):
                out.append(Finding("skill-frontmatter", h.rel(p), f"frontmatter {field}: is empty"))
        m = NAME_RE.search(fm)
        if m and m.group(1) != p.parent.name:
            out.append(Finding("skill-frontmatter", h.rel(p),
                               f"frontmatter name {m.group(1)!r} does not match its directory "
                               f"{p.parent.name!r}"))
        # 백틱 경로만 보면 `[guide](references/missing.md)` 형태를 놓친다.
        refs = set(re.findall(r"`(references/[^`\n]+)`", text))
        refs |= set(re.findall(r"\]\((references/[^)\n]+)\)", text))
        for ref in sorted(refs):
            if not (p.parent / ref.split("#")[0]).is_file():
                out.append(Finding("skill-frontmatter", h.rel(p), f"broken reference path: {ref}"))


def rule_orphan_agents(h: Harness, out: list[Finding]) -> None:
    """Agents nothing calls, and calls to agents that do not exist.

    This is the check that answers 'you generated twenty-seven agents — which of
    them ever runs?'. An agent no orchestrator references is cost with no path
    to value; a referenced agent that does not exist is a runtime failure.
    """
    if not h.agents:
        return
    defined = {h.agent_name(p) for p in h.agents}
    referenced: set[str] = set()
    for p in h.skills:
        text = p.read_text(encoding="utf-8")
        for a, b in SUBAGENT_REF_RE.findall(text):
            referenced.add(a or b)
        # 이전에는 이름이 본문에 «단어» 로 나오기만 하면 호출로 쳤다. 이름이
        # `build`·`review` 같은 일상어면 "we should build the binary" 한 줄에
        # 고아가 사라진다. 호출 문법으로만 인정한다.
        for name in defined:
            if re.search(rf"""(?:subagent_type|agentType|agent)\s*[:=]\s*["']{re.escape(name)}["']"""
                         rf"""|@{re.escape(name)}\b|`{re.escape(name)}`""", text):
                referenced.add(name)

    by_name = {h.agent_name(p): h.rel(p) for p in h.agents}
    for name in sorted(defined - referenced):
        out.append(Finding("orphan-agents", by_name.get(name, f".claude/agents/{name}.md"),
                           "no skill or orchestrator references this agent — "
                           "delete it or wire it in"))
    for name in sorted(referenced - defined):
        # 빌트인 타입과 유저 스코프 전역 에이전트는 프로젝트에 정의가 없는 것이
        # 정상이다. 그걸 «정의 없음» 으로 잡으면 전역 에이전트를 쓰는 하네스가
        # 전부 실패한다.
        if name in {"general-purpose", "Explore", "Plan"}:
            continue
        if (Path(os.path.expanduser("~/.claude/agents")) / f"{name}.md").is_file():
            continue
        out.append(Finding("orphan-agents", ".claude/skills/",
                           f"references agent {name!r}, which has no definition file"))


def rule_model_tiering(h: Harness, out: list[Finding]) -> None:
    """Every agent pinned to the same tier is the v1 antipattern returning.

    Only fires with three or more agents; below that, uniformity is not evidence
    of anything.
    """
    if len(h.agents) < 3:
        return
    tiers = {}
    for p in h.agents:
        fm = frontmatter(p.read_text(encoding="utf-8")) or ""
        m = MODEL_RE.search(fm)
        if m:
            tiers.setdefault(m.group(1), []).append(p.stem)
    # Uniformity alone is not a defect — identical work deserves an identical
    # tier. Only the specific v1 antipattern is flagged: everything pinned to
    # the most expensive tier, which is what the blanket `model: "opus"` rule
    # produced and what v2 set out to end.
    # `opus` 리터럴만 보면 claude-opus-4·claude-3-opus-… 로 일괄 고정한 경우를
    # 놓친다. 같은 안티패턴인데 모델 ID 표기만 다르다.
    opus_pinned = [n for tier, names in tiers.items() if "opus" in tier.lower() for n in names]
    if opus_pinned and len(opus_pinned) == len(h.agents):
        out.append(Finding("model-tiering", ".claude/agents/",
                           f"all {len(h.agents)} agents pinned to an opus-family model — "
                           f"this is the v1 blanket pin. Choose per task "
                           f"(complexity, duration, autonomy, latency) or inherit"))


RULES = {
    "agent-frontmatter": rule_agent_frontmatter,
    "agent-naming": rule_agent_naming,
    "agent-duplicates": rule_agent_duplicates,
    "agent-sections": rule_agent_sections,
    "dead-api": rule_dead_api,
    "user-scope-shadowing": rule_user_scope_shadowing,
    "skill-frontmatter": rule_skill_frontmatter,
    "orphan-agents": rule_orphan_agents,
    "model-tiering": rule_model_tiering,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", default=".", help="project root (default: cwd)")
    ap.add_argument("--only", action="append", choices=sorted(RULES),
                    help="run only the named rule (repeatable)")
    ap.add_argument("--list", action="store_true", help="list rule names and exit")
    args = ap.parse_args()

    if args.list:
        for name in sorted(RULES):
            print(name)
        return 0

    h = Harness(Path(args.path).resolve())
    if not h.exists():
        print(f"no harness found under {h.claude} — nothing to lint", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    selected = args.only or sorted(RULES)
    for name in selected:
        RULES[name](h, findings)

    if findings:
        print(f"harness-lint: {len(findings)} finding(s) in "
              f"{len(h.agents)} agent(s), {len(h.skills)} skill(s)", file=sys.stderr)
        for f in findings:
            print(f"- {f}", file=sys.stderr)
        return 1

    print(f"harness-lint: clean — {len(h.agents)} agent(s), {len(h.skills)} skill(s), "
          f"{len(selected)} rule(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
