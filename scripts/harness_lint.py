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
import os
import re
import sys
from pathlib import Path

# The factory is told to generate in the user's locale (Phase 1-7), so matching
# section headings by their Korean or English wording would reject a harness
# built exactly as instructed in Japanese or Chinese. The contract is that four
# sections exist, not what language names them — so count structure, not words.
REQUIRED_AGENT_SECTION_COUNT = 4

DEAD_API_TOKENS = ["TeamCreate", "TeamDelete", "team_name", "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"]
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
        for field in ("name:", "description:"):
            if field not in fm:
                out.append(Finding("agent-frontmatter", h.rel(p), f"frontmatter missing {field}"))
        # Deliberately NOT checking that name matches the filename. Resolution
        # is by `name`, so a divergence is legal; asserting otherwise would be a
        # check that enforces a convention while stating a falsehood about why.


def rule_agent_sections(h: Harness, out: list[Finding]) -> None:
    """Every agent carries the four contract sections, in whatever language."""
    for p in h.agents:
        body = p.read_text(encoding="utf-8")
        after_fm = FRONTMATTER_RE.sub("", body, count=1)
        sections = re.findall(r"^##\s+\S", after_fm, re.MULTILINE)
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
            if not hits:
                continue
            if any(neg.lower() in line.lower() for neg in DEAD_API_NEGATIONS):
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
        for field in ("name:", "description:"):
            if field not in fm:
                out.append(Finding("skill-frontmatter", h.rel(p), f"frontmatter missing {field}"))
        m = NAME_RE.search(fm)
        if m and m.group(1) != p.parent.name:
            out.append(Finding("skill-frontmatter", h.rel(p),
                               f"frontmatter name {m.group(1)!r} does not match its directory "
                               f"{p.parent.name!r}"))
        for ref in re.findall(r"`(references/[^`\n]+)`", text):
            if not (p.parent / ref).is_file():
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
        for name in defined:
            if re.search(rf"\b{re.escape(name)}\b", text):
                referenced.add(name)

    by_name = {h.agent_name(p): h.rel(p) for p in h.agents}
    for name in sorted(defined - referenced):
        out.append(Finding("orphan-agents", by_name.get(name, f".claude/agents/{name}.md"),
                           "no skill or orchestrator references this agent — "
                           "delete it or wire it in"))
    for name in sorted(referenced - defined):
        if name in {"general-purpose", "Explore", "Plan"}:
            continue  # built-in types
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
    if tiers.get("opus") and len(tiers["opus"]) == len(h.agents):
        out.append(Finding("model-tiering", ".claude/agents/",
                           f"all {len(h.agents)} agents pinned to model: opus — "
                           f"this is the v1 blanket pin. Choose per task "
                           f"(complexity, duration, autonomy, latency) or inherit"))


RULES = {
    "agent-frontmatter": rule_agent_frontmatter,
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
