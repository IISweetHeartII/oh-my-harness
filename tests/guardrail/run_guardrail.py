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
    path = repo / "skills" / "harness" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("name: harness", "name: not-the-directory-name", 1), encoding="utf-8")
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
}


# --------------------------------------------------------------------------
# harness-lint breakages — each corrupts a generated harness in one way
# --------------------------------------------------------------------------

def hl_agent_frontmatter(h: Path) -> str:
    p = h / ".claude" / "agents" / "billing-analyst.md"
    text = p.read_text()
    p.write_text("\n".join(l for l in text.splitlines() if not l.startswith("description:")))
    return "agent frontmatter lost its description"


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


LINT_CASES = {
    "agent-frontmatter": hl_agent_frontmatter,
    "agent-naming": hl_agent_naming,
    "agent-sections": hl_agent_sections,
    "dead-api": hl_dead_api,
    "user-scope-shadowing": hl_user_scope_shadowing,
    "skill-frontmatter": hl_skill_frontmatter,
    "orphan-agents": hl_orphan_agents,
    "model-tiering": hl_model_tiering,
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
    """Identical work deserves an identical tier — uniform is not a defect."""
    for name in ("billing-analyst", "billing-builder"):
        p = h / ".claude" / "agents" / f"{name}.md"
        p.write_text(p.read_text().replace("model: opus", "model: sonnet"))
    return "every agent on sonnet because the work is the same shape"


def make_namespaced(h: Path) -> str:
    """A project that declares a namespace and honours it must pass."""
    (h / ".claude" / "harness.json").write_text('{"agentNamespace": "billing"}\n')
    return "a declared agentNamespace that every agent honours"


VALID_VARIANTS = {
    "declared-namespace": make_namespaced,
    "japanese-harness": make_japanese,
    "name-differs-from-filename": make_name_differs,
    "uniform-sonnet-tier": make_uniform_sonnet,
}


def guardrail_valid_variants(failures: list[str], verbose: bool) -> None:
    """Prove the rules do not reject harnesses that are legitimately different.

    Breaking a rule and watching it fail only shows the rule fires. It says
    nothing about whether the rule is *right* — a wrong rule fails perfectly.
    These cases are the other half: inputs that must PASS.
    """
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        (home / ".claude" / "agents").mkdir(parents=True)
        for label, variant in VALID_VARIANTS.items():
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
    uncovered = sorted(set(known) - set(LINT_CASES))
    if uncovered:
        failures.append(f"harness-lint rules with no guardrail case: {', '.join(uncovered)}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        # A fake HOME so user-scope-shadowing is deterministic on any machine,
        # including CI, where ~/.claude/agents does not exist.
        home = Path(tmp) / "home"
        (home / ".claude" / "agents").mkdir(parents=True)
        (home / ".claude" / "agents" / "analyst.md").write_text("---\nname: analyst\n---\n")

        for rule, breaker in LINT_CASES.items():
            clean = Path(tmp) / f"clean-{rule}"
            shutil.copytree(CLEAN_FIXTURE, clean)
            before = run_lint(clean, rule, home)
            if before.returncode != 0:
                failures.append(f"harness-lint {rule}: fires on the clean fixture — proves nothing")
                if verbose:
                    print(before.stderr)
                continue

            broken = Path(tmp) / f"broken-{rule}"
            shutil.copytree(CLEAN_FIXTURE, broken)
            what = breaker(broken)
            after = run_lint(broken, rule, home)
            if after.returncode == 0:
                failures.append(f"harness-lint {rule}: did NOT fire after {what}")
            else:
                print(f"  ok  lint:{rule:20s} caught: {what}")
                if verbose:
                    print("      " + after.stderr.strip().replace("\n", "\n      "))


# --------------------------------------------------------------------------

def run_check(repo: Path, check: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--only", check],
        cwd=repo, capture_output=True, text=True,
    )


def copy_tree(dest: Path) -> None:
    shutil.copytree(
        ROOT, dest,
        ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"),
    )
    # fixtures-tracked asks git what it tracks, so the copy needs a git view.
    # Seed it from the real repository's index rather than the working tree, so
    # the copy inherits exactly what a fresh clone would get.
    subprocess.run(["git", "init", "-q"], cwd=dest, check=False,
                   capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, check=False,
                   capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

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
            if result.returncode == 0:
                failures.append(f"{check}: did NOT fail after {what}")
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

    print(f"\nGuardrail suite passed: {len(CASES)} repository checks + "
          f"{len(LINT_CASES)} harness-lint rules proven to fire on broken input, and "
          f"{len(VALID_VARIANTS)} legitimate variants proven to pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
