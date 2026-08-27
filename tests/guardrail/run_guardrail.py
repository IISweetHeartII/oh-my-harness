#!/usr/bin/env python3
"""Prove every repository check actually fails when its rule is broken.

A check nobody has watched fail is not a check. CI going green tells you the
current tree is clean; it does not tell you the gate would have caught a dirty
one. This suite answers the second question.

For each case it copies the working tree to a temp dir, applies one deliberate
breakage, runs `scripts/validate_repository.py --only <check>` against the copy,
and asserts a non-zero exit. It then re-runs the same check on the pristine copy
and asserts zero, so a check that fails unconditionally is caught too.

Usage:  python3 tests/guardrail/run_guardrail.py [--verbose]
Exit 0 = every gate behaved correctly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = Path("scripts/validate_repository.py")
HARNESS_LINT = ROOT / "scripts" / "harness_lint.py"
CLEAN_FIXTURE = ROOT / "tests" / "fixtures" / "clean-harness"
CASES_DIR = Path(__file__).resolve().parent / "cases"


# --------------------------------------------------------------------------
# breakages — each takes the temp repo root and makes exactly one thing wrong
# --------------------------------------------------------------------------

def break_required_files(repo: Path) -> str:
    (repo / "NOTICE").unlink()
    return "deleted NOTICE"


def break_manifest_conventions(repo: Path) -> str:
    """Re-declare a conventional path — the bug that made 2.3.1 fail to load."""
    path = repo / ".claude-plugin" / "plugin.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["hooks"] = "./hooks/hooks.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return "re-declared the auto-discovered hooks/hooks.json in plugin.json"


def break_plugin_manifests(repo: Path) -> str:
    path = repo / ".claude-plugin" / "marketplace.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["plugins"][0]["version"] = "0.0.0-wrong"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return "marketplace version no longer matches plugin.json"


def break_skill_frontmatter(repo: Path) -> str:
    """Rename the skill in frontmatter, whichever way the YAML spells it.

    Substituting the exact string `name: harness` made this case depend on one
    spelling; `name: "harness"` would have produced a false failure that looks
    like the gate broke rather than the fixture.
    """
    path = repo / "skills" / "harness" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    new_text, n = re.subn(r"""^name:[ \t]*["']?harness["']?[ \t]*$""",
                          "name: not-the-directory-name", text, count=1, flags=re.M)
    if not n:
        raise AssertionError("no `name: harness` line to rewrite in skills/harness/SKILL.md")
    path.write_text(new_text, encoding="utf-8")
    return "skill frontmatter name no longer matches its directory"


def break_link_existence(repo: Path) -> str:
    shutil.copy(CASES_DIR / "broken-link.md.fixture", repo / "docs" / "guardrail-broken-link.md")
    return "added a doc linking to a file that does not exist"


def break_dead_api(repo: Path) -> str:
    shutil.copy(CASES_DIR / "dead-api.md.fixture", repo / "docs" / "guardrail-dead-api.md")
    return "added a doc instructing the reader to call TeamCreate"


def break_dead_api_yaml(repo: Path) -> str:
    """Same rule, non-Markdown carrier — the gap that let the issue templates
    keep instructing readers to export a removed experimental flag."""
    shutil.copy(CASES_DIR / "dead-api.yml.fixture",
                repo / ".github" / "ISSUE_TEMPLATE" / "guardrail-dead-api.yml")
    return "added a YAML template instructing the reader to call TeamCreate"


def break_version_consistency(repo: Path) -> str:
    path = repo / ".claude-plugin" / "plugin.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = "9.9.9"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # keep the marketplace entry in step so only the CHANGELOG disagrees
    mpath = repo / ".claude-plugin" / "marketplace.json"
    mdata = json.loads(mpath.read_text(encoding="utf-8"))
    mdata["plugins"][0]["version"] = "9.9.9"
    mpath.write_text(json.dumps(mdata, ensure_ascii=False, indent=2), encoding="utf-8")
    return "plugin version bumped without a matching CHANGELOG release"


def break_change_notice(repo: Path) -> str:
    manifest = json.loads((repo / "docs" / "derived-files.json").read_text(encoding="utf-8"))
    inline = [p for p in manifest.get("modified", []) if p not in set(manifest.get("commentUnsupported", []))]
    if not inline:
        raise RuntimeError("no inline-notice file to strip; fixture cannot run")
    target = repo / inline[0]
    text = target.read_text(encoding="utf-8")
    stripped = "\n".join(
        line for line in text.splitlines() if "Modified from revfactory/harness" not in line
    )
    target.write_text(stripped + "\n", encoding="utf-8")
    return f"stripped the Apache-2.0 change notice from {inline[0]}"


def break_fixtures_tracked(repo: Path) -> str:
    """An untracked fixture file — the .gitignore trap that made CI diverge."""
    (repo / "tests" / "fixtures" / "clean-harness" / "UNTRACKED.md").write_text(
        "# a fixture file git never saw\n", encoding="utf-8")
    return "added a fixture file that git does not track"


def break_lint_rule_docs(repo: Path) -> str:
    """Add a rule to the linter that no document mentions — the 7-vs-9 drift.

    The linter grew two rules and two documents kept saying seven, including
    the fallback list a plugin-less user follows by hand.
    """
    path = repo / "scripts" / "harness_lint.py"
    text = path.read_text(encoding="utf-8")
    marker = 'RULES = {\n    "agent-frontmatter"'
    if marker not in text:
        raise AssertionError("could not find the RULES table to extend")
    text = text.replace(
        marker,
        "def rule_undocumented(h, out) -> None:\n    return\n\n\n"
        'RULES = {\n    "undocumented-rule": rule_undocumented,\n    "agent-frontmatter"',
        1)
    path.write_text(text, encoding="utf-8")
    return "added a lint rule that no document mentions"


def break_ci_runs_preflight(repo: Path) -> str:
    """Put the gate list back into CI — the drift preflight.sh exists to stop."""
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    text = text.replace("        run: bash scripts/preflight.sh",
                        "        run: python3 scripts/validate_repository.py", 1)
    wf.write_text(text, encoding="utf-8")
    return "CI calling one gate directly instead of scripts/preflight.sh"


def break_size_budget(repo: Path) -> str:
    path = repo / "skills" / "harness" / "SKILL.md"
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n" + "\n".join(f"padding line {i}" for i in range(600)) + "\n")
    return "padded skills/harness/SKILL.md past its line budget"


def break_readme_parity(repo: Path) -> str:
    path = repo / "README_JA.md"
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n## 翻訳がずれたことにするための余分な節\n")
    return "added a section to README_JA.md that README.md does not have"


CASES = {
    "required-files": break_required_files,
    "size-budget": break_size_budget,
    "fixtures-tracked": break_fixtures_tracked,
    "readme-parity": break_readme_parity,
    "plugin-manifests": break_plugin_manifests,
    "manifest-conventions": break_manifest_conventions,
    "skill-frontmatter": break_skill_frontmatter,
    "link-existence": break_link_existence,
    "dead-api": break_dead_api,
    "dead-api-yaml": break_dead_api_yaml,
    "version-consistency": break_version_consistency,
    "change-notice": break_change_notice,
    "lint-rule-docs": break_lint_rule_docs,
    "ci-runs-preflight": break_ci_runs_preflight,
}


# --------------------------------------------------------------------------
# harness-lint breakages — each corrupts a generated harness in one way
# --------------------------------------------------------------------------

def hl_agent_frontmatter(h: Path) -> str:
    p = h / ".claude" / "agents" / "billing-analyst.md"
    text = p.read_text()
    p.write_text("\n".join(l for l in text.splitlines() if not l.startswith("description:")))
    return "agent frontmatter lost its description"


def hl_agent_duplicates(h: Path) -> str:
    """Two files declaring the same name — one of them is unreachable."""
    src = h / ".claude" / "agents" / "billing-analyst.md"
    (h / ".claude" / "agents" / "second-copy.md").write_text(src.read_text())
    return "two agent files declaring the same name"


def hl_agent_naming(h: Path) -> str:
    """A bare generic role name — it silently replaces the user's global one."""
    src = h / ".claude" / "agents" / "billing-analyst.md"
    dst = h / ".claude" / "agents" / "analyst.md"
    dst.write_text(src.read_text().replace("name: billing-analyst", "name: analyst", 1))
    s = h / ".claude" / "skills" / "build" / "SKILL.md"
    with s.open("a", encoding="utf-8") as fh:
        fh.write('\nPhase 0: `Agent(subagent_type: "analyst")`\n')
    return "generated a bare 'analyst', squatting a generic role name"


def hl_agent_sections(h: Path) -> str:
    p = h / ".claude" / "agents" / "billing-analyst.md"
    text = p.read_text()
    p.write_text("\n".join(l for l in text.splitlines() if "## 작업 원칙" not in l))
    return "dropped a required contract section from an agent"


def hl_dead_api(h: Path) -> str:
    p = h / ".claude" / "skills" / "build" / "SKILL.md"
    with p.open("a", encoding="utf-8") as fh:
        fh.write("\nPhase 0: start the team with TeamCreate(team_name: \"billing\").\n")
    return "orchestrator instructs the removed TeamCreate API"


def hl_user_scope_shadowing(h: Path) -> str:
    # planted into the fake HOME by the runner; here we just collide with it
    src = h / ".claude" / "agents" / "billing-analyst.md"
    dst = h / ".claude" / "agents" / "analyst.md"
    dst.write_text(src.read_text().replace("name: billing-analyst", "name: analyst", 1))
    return "generated an agent named 'analyst', shadowing the user's global one"


def hl_skill_frontmatter(h: Path) -> str:
    p = h / ".claude" / "skills" / "build" / "SKILL.md"
    p.write_text(p.read_text().replace("name: build", "name: not-the-directory", 1))
    return "skill frontmatter name no longer matches its directory"


def hl_orphan_agents(h: Path) -> str:
    p = h / ".claude" / "agents" / "billing-ghost.md"
    p.write_text((h / ".claude" / "agents" / "billing-analyst.md").read_text()
                 .replace("billing-analyst", "billing-ghost"))
    return "added an agent no orchestrator references"


def hl_model_tiering(h: Path) -> str:
    third = h / ".claude" / "agents" / "billing-checker.md"
    third.write_text((h / ".claude" / "agents" / "billing-analyst.md").read_text()
                     .replace("billing-analyst", "billing-checker"))
    for name in ("billing-analyst", "billing-builder", "billing-checker"):
        p = h / ".claude" / "agents" / f"{name}.md"
        p.write_text(p.read_text().replace("model: sonnet", "model: opus"))
    # keep it referenced so orphan-agents is not what fires
    s = h / ".claude" / "skills" / "build" / "SKILL.md"
    with s.open("a", encoding="utf-8") as fh:
        fh.write('\nPhase 3: `Agent(subagent_type: "billing-checker")`\n')
    return "pinned every agent to the same model tier"


def hl_agent_sections_tilde(h: Path) -> str:
    """Four ## headings inside a ~~~ fence are examples, not sections.

    A valid CommonMark fence the old backtick-only regex did not know about.
    Reproduced by the adversarial review: an agent with no real sections at
    all passed on the strength of its output example.
    """
    p = h / ".claude" / "agents" / "billing-analyst.md"
    body = re.sub(r"^##\s+.*$", "(was a section)", p.read_text(), flags=re.M)
    p.write_text(body + "\n\n~~~text\n## one\n## two\n## three\n## four\n~~~\n")
    return "four ## headings inside a ~~~ fence and no real sections"


def hl_dead_api_multiline(h: Path) -> str:
    """team_name inside an Agent(...) call written across several lines."""
    p = h / ".claude" / "skills" / "build" / "SKILL.md"
    with p.open("a", encoding="utf-8") as fh:
        fh.write('\nPhase 9:\n```\nAgent(\n    subagent_type: "billing-analyst",\n'
                 '    team_name: "billing",\n)\n```\n')
    return "team_name inside a multi-line Agent(...) call"


def hl_orphan_workflow_ghost(h: Path) -> str:
    """A workflow calling an agent that does not exist.

    Workflow scripts are the main v2 execution mode and the linter did not
    read them, so this failed only at runtime.
    """
    wf = h / ".claude" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "nightly.ts").write_text(
        "export const meta = { name: 'nightly', description: 'x' }\n"
        "await agent('run the sweep', { agentType: 'billing-ghost' })\n", encoding="utf-8")
    return "a workflow calling an agent with no definition"


def hl_orphan_workflow_template_literal(h: Path) -> str:
    """A name inside a template literal is a log message, not a call.

    Workflow files are code. Applying the prose fallbacks (backticks, @name) to
    them marks an agent as wired in because its name appeared in a log line.
    """
    ghost = h / ".claude" / "agents" / "billing-ghost.md"
    ghost.write_text((h / ".claude" / "agents" / "billing-analyst.md").read_text()
                     .replace("billing-analyst", "billing-ghost"))
    wf = h / ".claude" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "nightly.ts").write_text(
        "export const meta = { name: 'nightly', description: 'x' }\n"
        "log(`starting billing-ghost sweep`)\n", encoding="utf-8")
    return "an agent named only inside a template literal in a workflow"


LINT_CASES = {
    "agent-frontmatter": hl_agent_frontmatter,
    "agent-naming": hl_agent_naming,
    "agent-duplicates": hl_agent_duplicates,
    "agent-sections": hl_agent_sections,
    "dead-api": hl_dead_api,
    "user-scope-shadowing": hl_user_scope_shadowing,
    "skill-frontmatter": hl_skill_frontmatter,
    "orphan-agents": hl_orphan_agents,
    "model-tiering": hl_model_tiering,
    # extra carriers for a rule already covered above — same gate, input the
    # first version of the rule did not look at
    "agent-sections-tilde-fence": hl_agent_sections_tilde,
    "dead-api-multiline-call": hl_dead_api_multiline,
    "orphan-agents-workflow-ghost": hl_orphan_workflow_ghost,
    "orphan-agents-template-literal": hl_orphan_workflow_template_literal,
}

# case name -> the rule it actually exercises, for the cases that are extra
# carriers rather than gates of their own
LINT_ALIASES = {
    "agent-sections-tilde-fence": "agent-sections",
    "dead-api-multiline-call": "dead-api",
    "orphan-agents-workflow-ghost": "orphan-agents",
    "orphan-agents-template-literal": "orphan-agents",
}


def run_lint(harness: Path, rule: str, home: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(
        [sys.executable, str(HARNESS_LINT), str(harness), "--only", rule],
        capture_output=True, text=True, env=env,
    )


def make_japanese(h: Path) -> str:
    """A harness generated in Japanese, exactly as Phase 1-7 instructs."""
    p = h / ".claude" / "agents" / "billing-analyst.md"
    s = p.read_text()
    for ko, ja in (("## 핵심 역할", "## 主な役割"), ("## 작업 원칙", "## 作業原則"),
                   ("## 입력/출력 프로토콜", "## 入出力プロトコル"), ("## 협업", "## 連携")):
        s = s.replace(ko, ja)
    p.write_text(s)
    return "an agent written in Japanese"


def make_name_differs(h: Path) -> str:
    """name diverging from the filename is legal — resolution is by name."""
    p = h / ".claude" / "agents" / "billing-analyst.md"
    p.write_text(p.read_text().replace("name: billing-analyst", "name: analyst-for-billing", 1))
    s = h / ".claude" / "skills" / "build" / "SKILL.md"
    s.write_text(s.read_text().replace("billing-analyst", "analyst-for-billing"))
    return "an agent whose name differs from its filename"


def make_uniform_sonnet(h: Path) -> str:
    """Identical work deserves an identical tier — uniform is not a defect.

    Three agents, not two: `model-tiering` returns early below three, so a
    two-agent variant proved the rule accepted it without running a line of
    it. The variant has to reach the rule body to mean anything.
    """
    third = h / ".claude" / "agents" / "billing-checker.md"
    third.write_text((h / ".claude" / "agents" / "billing-analyst.md").read_text()
                     .replace("billing-analyst", "billing-checker"))
    s = h / ".claude" / "skills" / "build" / "SKILL.md"
    with s.open("a", encoding="utf-8") as fh:
        fh.write('\nPhase 3: `Agent(subagent_type: "billing-checker")`\n')
    for name in ("billing-analyst", "billing-builder", "billing-checker"):
        p = h / ".claude" / "agents" / f"{name}.md"
        p.write_text(p.read_text().replace("model: opus", "model: sonnet"))
    return "three agents all on sonnet because the work is the same shape"


def make_namespaced(h: Path) -> str:
    """A project that declares a namespace and honours it must pass."""
    (h / ".claude" / "harness.json").write_text('{"agentNamespace": "billing"}\n')
    return "a declared agentNamespace that every agent honours"


def make_global_name_differs(h: Path) -> str:
    """Calling a global agent whose file is named something else is legal.

    Resolution is by frontmatter name on both sides. Checking the global side
    by filename reported this valid harness as calling an undefined agent.
    """
    s = h / ".claude" / "skills" / "build" / "SKILL.md"
    s.write_text(s.read_text() + '\nPhase 9: `Agent(subagent_type: "global-helper")`\n')
    return "a call to a global agent whose filename differs from its name"


def make_sports_team_name(h: Path) -> str:
    """`team_name` outside any Claude call is an ordinary column name."""
    s = h / ".claude" / "skills" / "build" / "SKILL.md"
    s.write_text(s.read_text() + "\n## Roster import\nEach roster row carries a "
                 "`team_name` column.\nSort the rows by team_name before writing them out.\n")
    return "team_name as a domain column, in no Claude call"


def make_workflow_only_agent(h: Path) -> str:
    """An agent only a workflow script calls is wired in, not orphaned."""
    third = h / ".claude" / "agents" / "billing-checker.md"
    third.write_text((h / ".claude" / "agents" / "billing-analyst.md").read_text()
                     .replace("billing-analyst", "billing-checker"))
    wf = h / ".claude" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "nightly.ts").write_text(
        "export const meta = { name: 'nightly', description: 'x' }\n"
        "await agent('check the totals', { agentType: 'billing-checker' })\n", encoding="utf-8")
    return "an agent referenced only from a workflow script"


def make_declared_uniform_tier(h: Path) -> str:
    """Three all-opus specialists, with the reason written down."""
    third = h / ".claude" / "agents" / "billing-checker.md"
    third.write_text((h / ".claude" / "agents" / "billing-analyst.md").read_text()
                     .replace("billing-analyst", "billing-checker"))
    s = h / ".claude" / "skills" / "build" / "SKILL.md"
    with s.open("a", encoding="utf-8") as fh:
        fh.write('\nPhase 3: `Agent(subagent_type: "billing-checker")`\n')
    for name in ("billing-analyst", "billing-builder", "billing-checker"):
        p = h / ".claude" / "agents" / f"{name}.md"
        p.write_text(p.read_text().replace("model: sonnet", "model: opus"))
    (h / ".claude" / "harness.json").write_text(json.dumps({
        "uniformTierRationale": "Every role here reasons over incomplete evidence "
                                "and a wrong call costs a re-run of the whole night."
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return "three all-opus agents with the reason recorded in harness.json"


VALID_VARIANTS = {
    "declared-namespace": make_namespaced,
    "japanese-harness": make_japanese,
    "name-differs-from-filename": make_name_differs,
    "uniform-sonnet-tier": make_uniform_sonnet,
    "global-agent-name-differs": make_global_name_differs,
    "sports-team-name": make_sports_team_name,
    "workflow-only-agent": make_workflow_only_agent,
    "declared-uniform-tier": make_declared_uniform_tier,
}

# variants that need something in the fake global agent directory
VARIANT_GLOBAL_AGENTS = {
    "global-agent-name-differs": ("different-filename.md",
                                  "---\nname: global-helper\ndescription: a global agent\n---\n"),
}


def guardrail_valid_variants(failures: list[str], verbose: bool) -> None:
    """Prove the rules do not reject harnesses that are legitimately different.

    Breaking a rule and watching it fail only shows the rule fires. It says
    nothing about whether the rule is *right* — a wrong rule fails perfectly.
    These cases are the other half: inputs that must PASS.
    """
    with tempfile.TemporaryDirectory() as tmp:
        for label, variant in VALID_VARIANTS.items():
            # each variant gets its own global agent directory, so one variant's
            # global agent cannot silently satisfy another's check
            home = Path(tmp) / f"home-{label}"
            (home / ".claude" / "agents").mkdir(parents=True)
            if label in VARIANT_GLOBAL_AGENTS:
                fname, body = VARIANT_GLOBAL_AGENTS[label]
                (home / ".claude" / "agents" / fname).write_text(body, encoding="utf-8")
            h = Path(tmp) / label
            shutil.copytree(CLEAN_FIXTURE, h)
            what = variant(h)
            res = subprocess.run(
                [sys.executable, str(HARNESS_LINT), str(h)],
                capture_output=True, text=True, env=dict(os.environ, HOME=str(home)),
            )
            if res.returncode != 0:
                failures.append(f"valid variant rejected — {what}: {res.stderr.strip()}")
            else:
                print(f"  ok  valid:{label:22s} accepted: {what}")


def guardrail_harness_lint(failures: list[str], verbose: bool) -> None:
    """Prove each harness-lint rule fires on a generated harness that breaks it."""
    known = subprocess.run([sys.executable, str(HARNESS_LINT), "--list"],
                           capture_output=True, text=True).stdout.split()
    covered = {LINT_ALIASES.get(c, c) for c in LINT_CASES}
    uncovered = sorted(set(known) - covered)
    if uncovered:
        failures.append(f"harness-lint rules with no guardrail case: {', '.join(uncovered)}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        # A fake HOME so user-scope-shadowing is deterministic on any machine,
        # including CI, where ~/.claude/agents does not exist.
        home = Path(tmp) / "home"
        (home / ".claude" / "agents").mkdir(parents=True)
        (home / ".claude" / "agents" / "analyst.md").write_text("---\nname: analyst\n---\n")

        for case, breaker in LINT_CASES.items():
            rule = LINT_ALIASES.get(case, case)
            clean = Path(tmp) / f"clean-{case}"
            shutil.copytree(CLEAN_FIXTURE, clean)
            before = run_lint(clean, rule, home)
            if before.returncode != 0:
                failures.append(f"harness-lint {case}: fires on the clean fixture — proves nothing")
                if verbose:
                    print(before.stderr)
                continue

            broken = Path(tmp) / f"broken-{case}"
            shutil.copytree(CLEAN_FIXTURE, broken)
            what = breaker(broken)
            after = run_lint(broken, rule, home)
            why = verdict(after, rule)
            if why:
                tail = after.stderr.strip().splitlines()[-1][:120] if after.stderr.strip() else "(no stderr)"
                failures.append(f"harness-lint {case}: {why} — not proof it caught {what}\n"
                                f"      {tail}")
            else:
                print(f"  ok  lint:{case:26s} caught: {what}")
                if verbose:
                    print("      " + after.stderr.strip().replace("\n", "\n      "))


# --------------------------------------------------------------------------

def verdict(result: subprocess.CompletedProcess, gate: str) -> str | None:
    """Return None if this run is real proof the rule fired, else why it is not.

    Three things must all hold, and the third is the one that was missing:

      1. non-zero exit                    — something was rejected
      2. the rule names itself in stderr  — *that* rule, not some other
      3. exit code is exactly 1           — findings, not an internal error

    Both checkers reserve 1 for findings and 2+ for "could not run". Without
    the third condition a checker that dies with `[required-files] internal
    checker failure` and exit 2 is counted as a clean catch — reproduced by
    the adversarial review, and it passed the whole suite.
    """
    if result.returncode == 0:
        return "did NOT fail"
    if "Traceback" in result.stderr:
        return "crashed with a traceback"
    if result.returncode != 1:
        return (f"exited {result.returncode}, not 1 — that is the "
                f"'could not run' code, not a finding")
    if f"[{gate}]" not in result.stderr and f"- {gate}" not in result.stderr:
        return "exited non-zero but never named the rule"
    return None


def run_check(repo: Path, check: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--only", check],
        cwd=repo, capture_output=True, text=True,
    )


def copy_tree(dest: Path) -> None:
    """Copy the working tree, but keep git's view of what is *tracked*.

    Two things have to be true at once and the first version had only one:

      · uncommitted edits must be under test, or running this before a commit
        checks the previous commit instead of the change in front of you
      · a file git does not track must stay untracked in the copy, or
        `fixtures-tracked` cannot see the .gitignore trap it exists to catch

    `git add -A` satisfied the first and destroyed the second — it promoted
    every untracked file, so the breakage was tracked by the time the gate
    looked. Copying the tree and then staging only the paths the real
    repository tracks keeps both.
    """
    shutil.copytree(
        ROOT, dest,
        ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"),
    )
    subprocess.run(["git", "init", "-q"], cwd=dest, check=False, capture_output=True)
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                             check=False, capture_output=True).stdout
    subprocess.run(
        ["git", "add", "--pathspec-from-file=-", "--pathspec-file-nul"],
        cwd=dest, input=tracked, check=False, capture_output=True,
    )


def self_test() -> int:
    """Test the judge itself, on the shapes that fooled it before.

    Every `ok ... caught:` line in this suite is only worth what `verdict()`
    is worth. It has been wrong twice: once counting a crash as a catch, once
    counting an internal error that happened to print the rule name. Both are
    pinned here so they cannot come back quietly.
    """
    class R:  # a stand-in for CompletedProcess
        def __init__(self, returncode: int, stderr: str) -> None:
            self.returncode, self.stderr = returncode, stderr

    cases = [
        ("clean exit is not a catch", R(0, ""), False),
        ("crash with a traceback is not a catch",
         R(1, "Traceback (most recent call last):\n  ...\n[required-files] x"), False),
        ("internal error that prints the rule name is not a catch",
         R(2, "- [required-files] internal checker failure"), False),
        ("non-zero without naming the rule is not a catch",
         R(1, "- [some-other-rule] something else"), False),
        ("exit 1 naming the rule IS a catch",
         R(1, "Repository validation failed:\n- [required-files] NOTICE is missing"), True),
    ]
    fail = 0
    for label, result, should_pass in cases:
        why = verdict(result, "required-files")
        accepted = why is None
        if accepted == should_pass:
            print(f"  ok  {label}")
        else:
            print(f"FAIL {label}: verdict={why!r}")
            fail = 1
    print("self-test passed" if not fail else "self-test FAILED")
    return fail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--self-test", action="store_true",
                        help="test the pass/fail judge itself and exit")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    known = subprocess.run(
        [sys.executable, str(VALIDATOR), "--list"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.split()
    # dead-api-yaml exercises the dead-api check through a non-Markdown file,
    # so it is an extra case rather than a check of its own.
    ALIASES = {"dead-api-yaml": "dead-api"}
    uncovered = sorted(set(known) - set(CASES) - set(ALIASES.values()))
    if uncovered:
        print(f"FAIL: checks with no guardrail case: {', '.join(uncovered)}", file=sys.stderr)
        return 1

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        pristine = Path(tmp) / "pristine"
        copy_tree(pristine)

        for check, breaker in CASES.items():
            # 1. the pristine tree must pass, or the case proves nothing
            gate = ALIASES.get(check, check)
            clean = run_check(pristine, gate)
            if clean.returncode != 0:
                failures.append(f"{check}: fails on the pristine tree — cannot prove anything")
            elif gate not in clean.stdout:
                # 통과 메시지가 그 규칙 이름을 대지 못하면, 그 규칙은 «돌지 않은» 것이다.
                failures.append(f"{check}: pristine run passed without naming the rule — "
                                f"the checker may not implement it at all")
                if args.verbose:
                    print(clean.stderr)
                continue

            # 2. the broken tree must fail
            broken = Path(tmp) / f"broken-{check}"
            copy_tree(broken)
            try:
                what = breaker(broken)
            except Exception as exc:  # a fixture that cannot run is a failure
                failures.append(f"{check}: fixture could not be applied: {exc}")
                continue

            result = run_check(broken, gate)
            why = verdict(result, gate)
            if why:
                tail = result.stderr.strip().splitlines()[-1][:120] if result.stderr.strip() else "(no stderr)"
                failures.append(f"{check}: {why} — not proof it caught {what}\n"
                                f"      {tail}")
            else:
                print(f"  ok  {check:22s} caught: {what}")
                if args.verbose:
                    print("      " + result.stderr.strip().replace("\n", "\n      "))
            shutil.rmtree(broken)

    guardrail_harness_lint(failures, args.verbose)
    guardrail_valid_variants(failures, args.verbose)

    if failures:
        print("\nGuardrail suite failed:", file=sys.stderr)
        for f in failures:
            print(f"- {f}", file=sys.stderr)
        return 1

    repo_rules = len({ALIASES.get(c, c) for c in CASES})
    lint_rules = len({LINT_ALIASES.get(c, c) for c in LINT_CASES})
    print(f"\nGuardrail suite passed: {repo_rules} repository rules "
          f"({len(CASES)} cases) + {lint_rules} harness-lint rules "
          f"({len(LINT_CASES)} cases) proven to fire on broken input, and "
          f"{len(VALID_VARIANTS)} legitimate variants proven to pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
