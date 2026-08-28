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

# How many contract sections harness-lint requires. Read from the linter so this
# suite cannot drift from it — a fixture with fewer headings than the threshold
# fires for the wrong reason and proves nothing.
REQUIRED_SECTIONS = int(re.search(
    r"^REQUIRED_AGENT_SECTION_COUNT\s*=\s*(\d+)",
    HARNESS_LINT.read_text(encoding="utf-8"), re.M).group(1))


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


def break_ci_preflight_comment_only(repo: Path) -> str:
    """CI stops running preflight while the header comment still names it.

    The first version of this gate searched the whole file, so the comment
    satisfied it and a workflow running `echo validation-skipped` passed.
    """
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    if "        run: bash scripts/preflight.sh" not in text:
        raise AssertionError("expected a run: step invoking preflight.sh")
    wf.write_text(text.replace("        run: bash scripts/preflight.sh",
                               "        run: echo validation-skipped", 1), encoding="utf-8")
    return "CI running nothing while only a comment still names preflight.sh"


def break_readme_section_count(repo: Path) -> str:
    """A README that states the old contract size.

    The gate checked the two documents it was written against and reported
    clean while all three READMEs told readers four sections and seven rules.
    """
    p = repo / "README.md"
    text = p.read_text(encoding="utf-8")
    new, n = re.subn(r"(`agent-sections`.*?Fewer than )5( contract sections)",
                     r"\g<1>4\g<2>", text, count=1)
    if not n:
        raise AssertionError("no agent-sections row stating 5 sections in README.md")
    p.write_text(new, encoding="utf-8")
    return "a README telling readers the old contract size"


def break_readme_rule_name(repo: Path) -> str:
    """A README that stops naming an implemented rule.

    The section-count case fires on the count alone, so removing the
    rule-name coverage entirely went unnoticed — one case cannot prove two
    independent halves of a check.
    """
    p = repo / "README_KO.md"
    text = p.read_text(encoding="utf-8")
    out = [l for l in text.splitlines(keepends=True) if "`agent-duplicates`" not in l]
    if len(out) == len(text.splitlines(keepends=True)):
        raise AssertionError("README_KO.md never mentioned agent-duplicates")
    p.write_text("".join(out), encoding="utf-8")
    return "a README that stopped naming an implemented rule"


def break_ci_preflight_shell_comment(repo: Path) -> str:
    """The run: step is commented out — it executes nothing."""
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    if "        run: bash scripts/preflight.sh" not in text:
        raise AssertionError("expected a run: step invoking preflight.sh")
    wf.write_text(text.replace(
        "        run: bash scripts/preflight.sh",
        "        run: |\n          echo skipping for now\n"
        "          # bash scripts/preflight.sh\n", 1), encoding="utf-8")
    return "the real call commented out behind a placeholder command"


def break_preflight_stage_removed(repo: Path) -> str:
    """Delete the line that runs the judge's self-test.

    This exact removal, together with a broken verdict(), produced exit 0 —
    the gates were all present and the line calling one of them was not.
    """
    p = repo / "scripts" / "preflight.sh"
    text = p.read_text(encoding="utf-8")
    line = 'run "guardrail self-test" python3 tests/guardrail/run_guardrail.py --self-test\n'
    if line not in text:
        raise AssertionError("preflight.sh no longer runs the self-test the way this case expects")
    p.write_text(text.replace(line, "", 1), encoding="utf-8")
    return "preflight no longer running the judge's self-test"


def break_preflight_stage_swapped(repo: Path) -> str:
    """Keep the stage count but make the stage do nothing."""
    p = repo / "scripts" / "preflight.sh"
    text = p.read_text(encoding="utf-8")
    old = 'run "guardrail self-test" python3 tests/guardrail/run_guardrail.py --self-test'
    if old not in text:
        raise AssertionError("preflight.sh no longer runs the self-test the way this case expects")
    p.write_text(text.replace(old, 'run "guardrail self-test" echo skipping', 1), encoding="utf-8")
    return "a preflight stage replaced by a no-op that keeps the count right"


def break_preflight_runner(repo: Path) -> str:
    """Keep the call line and the stage count; make the runner skip the command.

    The stage list still names the self-test and STAGES_EXPECTED still agrees
    with it, yet the judge is never run. Watching the call line is not watching
    the run — the gate has to pin the runner itself.
    """
    p = repo / "scripts" / "preflight.sh"
    text = p.read_text(encoding="utf-8")
    old = r"""run() { printf '\n== %s\n' "$1"; shift; stages_run=$((stages_run + 1)); "$@" || fail=1; }"""
    if old not in text:
        raise AssertionError("preflight.sh's run() is not the shape this case rewrites")
    new = (r"""run() { printf '\n== %s\n' "$1"; shift; stages_run=$((stages_run + 1)); """
           r"""case "$*" in *--self-test*) return 0;; esac; "$@" || fail=1; }""")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return "a runner that counts a stage it never executes"


def break_ci_preflight_echo(repo: Path) -> str:
    """CI names preflight inside a real run: step, and only prints it.

    Reverting `_invokes` to `script in command` leaves every other CI case
    green — those are caught by comment stripping, not by argv position. This
    is the case that goes red when the substring version comes back.
    """
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    if "        run: bash scripts/preflight.sh" not in text:
        raise AssertionError("expected a run: step invoking preflight.sh")
    wf.write_text(text.replace("        run: bash scripts/preflight.sh",
                               "        run: echo scripts/preflight.sh", 1), encoding="utf-8")
    return "CI echoing the gate's name instead of running it"


def break_dead_api_stale_allowlist(repo: Path) -> str:
    """An exemption for a line that does not exist.

    Deleting the stale-entry loop entirely left the suite green: every other
    dead-api case is about a *missing* exemption. A stale one is the dangerous
    direction — it pre-approves whatever text lands on that key next.
    """
    p = repo / "docs" / "dead-api-allowlist.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["allow"].append({
        "path": "docs/no-such-file.md",
        "token": "TeamCreate",
        "sha": "0123456789abcdef",
        "reason": "a line that was deleted long ago",
    })
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return "an allowlist entry whose line no longer exists"


def break_dead_api_build_dir(repo: Path) -> str:
    """A removed API under docs/build/ — a directory this repository owns.

    `build` was matched against any path part, so anything under docs/build/
    fell out of the scan. Ownership is the boundary; the word is not.
    """
    d = repo / "docs" / "build"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(CASES_DIR / "dead-api.md.fixture", d / "guardrail-dead-api.md")
    return "a removed API in docs/build/, which this repository writes"


def break_preflight_exit_code(repo: Path) -> str:
    """`exit 0` in place of `exit $fail`.

    Every gate can go red and the script still reports success. No self-check
    inside preflight can see this — the script cannot inspect its own exit
    code — so the pairing is this gate plus the integrity step CI runs after.
    """
    p = repo / "scripts" / "preflight.sh"
    text = p.read_text(encoding="utf-8")
    if "\nexit $fail\n" not in text:
        raise AssertionError("preflight.sh no longer ends with `exit $fail`")
    p.write_text(text.replace("\nexit $fail\n", "\nexit 0\n", 1), encoding="utf-8")
    return "preflight reporting success no matter what its stages did"


def break_preflight_runner_duplicate(repo: Path) -> str:
    """A second run() definition; the canonical first one becomes decoration."""
    p = repo / "scripts" / "preflight.sh"
    text = p.read_text(encoding="utf-8")
    call = 'run "guardrail self-test"'
    if call not in text:
        raise AssertionError("preflight.sh no longer has the self-test call line")
    tamper = ('run() { printf \'\\n== %s\\n\' "$1"; shift; stages_run=$((stages_run + 1)); "$@" || fail=1; }'.replace('"$@" || fail=1; }',
                                'case "$*" in *--self-test*) return 0;; esac; "$@" || fail=1; }'))
    p.write_text(text.replace(call, tamper + "\n" + call, 1), encoding="utf-8")
    return "a second run() definition that overrides the canonical one"


def break_preflight_runner_shadow(repo: Path) -> str:
    """A shell function named after the interpreter — every stage becomes a no-op."""
    p = repo / "scripts" / "preflight.sh"
    text = p.read_text(encoding="utf-8")
    call = 'run "guardrail self-test"'
    if call not in text:
        raise AssertionError("preflight.sh no longer has the self-test call line")
    p.write_text(text.replace(call, 'python3() { return 0; }\n' + call, 1), encoding="utf-8")
    return "a shell function named python3 shadowing the interpreter"


def break_ci_integrity_step(repo: Path) -> str:
    """CI drops the step that does not trust preflight's exit code."""
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    line = "        run: python3 scripts/validate_repository.py --only preflight-stages\n"
    if line not in text:
        raise AssertionError("validation.yml has no integrity step to remove")
    wf.write_text(text.replace(line, "        run: echo integrity skipped\n", 1),
                  encoding="utf-8")
    return "CI dropping the step that checks preflight's own integrity"


def break_ci_nest_switch(repo: Path) -> str:
    """CI setting the variable that switches off the enforcement check."""
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    line = "        run: bash scripts/preflight.sh\n"
    if line not in text:
        raise AssertionError("validation.yml no longer runs preflight the way this case expects")
    wf.write_text(text.replace(
        line, "        run: OH_MY_HARNESS_GUARDRAIL_NEST=1 bash scripts/preflight.sh\n", 1),
        encoding="utf-8")
    return "CI switching off the check that preflight enforces its gates"


def break_guardrail_section(repo: Path) -> str:
    """Delete the line that runs one whole section of this suite.

    Nothing inside the suite notices: the summary sentence gets shorter and
    every remaining case still passes. Same shape as the preflight stage that
    nobody was watching, one level in.
    """
    p = repo / "tests" / "guardrail" / "run_guardrail.py"
    text = p.read_text(encoding="utf-8")
    line = "    guardrail_preflight_enforces(failures, args.verbose)\n"
    if line not in text:
        raise AssertionError("the suite no longer calls guardrail_preflight_enforces")
    p.write_text(text.replace(line, "", 1), encoding="utf-8")
    return "a whole guardrail section that nothing calls any more"


def break_preflight_exit_before(repo: Path) -> str:
    """`exit 0` above the stages, with the real `exit $fail` still below it.

    Asking only whether the line exists let this through: the script returns
    before any stage runs, and the canonical last line is untouched.
    """
    p = repo / "scripts" / "preflight.sh"
    text = p.read_text(encoding="utf-8")
    call = 'run "guardrail self-test"'
    if call not in text:
        raise AssertionError("preflight.sh no longer has the self-test call line")
    p.write_text(text.replace(call, "exit 0\n" + call, 1), encoding="utf-8")
    return "an early `exit 0` with the real exit line still at the bottom"


def break_preflight_function_keyword(repo: Path) -> str:
    """`function run { ... }` — bash's other definition syntax.

    The duplicate/shadow checks only recognised `name()`, so the canonical
    definition could stay in place while this one actually ran.
    """
    p = repo / "scripts" / "preflight.sh"
    text = p.read_text(encoding="utf-8")
    call = 'run "guardrail self-test"'
    if call not in text:
        raise AssertionError("preflight.sh no longer has the self-test call line")
    p.write_text(text.replace(
        call, 'function run { stages_run=$((stages_run + 1)); return 0; }\n' + call, 1),
        encoding="utf-8")
    return "a `function run { }` no-op overriding the canonical runner"


def break_enforcement_emptied(repo: Path) -> str:
    """The enforcement section still runs, with nothing left to measure."""
    p = repo / "tests" / "guardrail" / "run_guardrail.py"
    text = p.read_text(encoding="utf-8")
    start = text.index("PREFLIGHT_ENFORCEMENT = [")
    end = text.index("\n]\n", start) + len("\n]\n")
    p.write_text(text[:start] + "PREFLIGHT_ENFORCEMENT = [\n]\n" + text[end:],
                 encoding="utf-8")
    return "an emptied enforcement list — the section runs and proves nothing"


def break_ci_nest_job_env(repo: Path) -> str:
    """The switch set at job level instead of inside a run: step."""
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    marker = "    runs-on: ubuntu-latest\n"
    if marker not in text:
        raise AssertionError("validation.yml no longer declares runs-on the expected way")
    wf.write_text(text.replace(
        marker, marker + '    env:\n      OH_MY_HARNESS_GUARDRAIL_NEST: "1"\n', 1),
        encoding="utf-8")
    return "the enforcement switch set as a job-level env instead of in a run: step"


def break_dead_api_duplicate_line(repo: Path) -> str:
    """A second, byte-identical occurrence of an allowlisted line.

    Keyed on path + token + line-hash alone, the two occurrences shared one
    key, so approving the first quietly approved the second.
    """
    p = repo / "docs" / "dead-api-allowlist.json"
    entry = json.loads(p.read_text(encoding="utf-8"))["allow"][0]
    target = repo / entry["path"]
    text = target.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    hit = next((i for i, l in enumerate(lines) if entry["token"] in l), None)
    if hit is None:
        raise AssertionError(f"{entry['path']} no longer contains {entry['token']}")
    lines.insert(hit + 1, lines[hit])
    target.write_text("".join(lines), encoding="utf-8")
    return "a second identical occurrence riding on the first one's exemption"


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
    "readme-rule-docs": break_readme_section_count,
    "readme-rule-name": break_readme_rule_name,
    "ci-preflight-shell-comment": break_ci_preflight_shell_comment,
    "preflight-stages": break_preflight_stage_removed,
    "preflight-stage-swapped": break_preflight_stage_swapped,
    "ci-runs-preflight": break_ci_runs_preflight,
    "ci-preflight-comment-only": break_ci_preflight_comment_only,
    "ci-preflight-echo-only": break_ci_preflight_echo,
    "preflight-run-tampered": break_preflight_runner,
    "dead-api-stale-allowlist": break_dead_api_stale_allowlist,
    "dead-api-build-dir": break_dead_api_build_dir,
    "preflight-exit-code": break_preflight_exit_code,
    "preflight-runner-duplicate": break_preflight_runner_duplicate,
    "preflight-runner-shadow": break_preflight_runner_shadow,
    "ci-integrity-step": break_ci_integrity_step,
    "ci-nest-switch": break_ci_nest_switch,
    "guardrail-section-removed": break_guardrail_section,
    "preflight-exit-before": break_preflight_exit_before,
    "preflight-function-keyword": break_preflight_function_keyword,
    "enforcement-emptied": break_enforcement_emptied,
    "ci-nest-job-env": break_ci_nest_job_env,
    "dead-api-duplicate-line": break_dead_api_duplicate_line,
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
    # As many fake headings as the contract requires. With fewer, a checker that
    # does not know tildes still counts too few and fires — so the case would
    # pass for the wrong reason and prove nothing about tilde handling.
    fence = "\n".join(f"## fake {i}" for i in range(1, REQUIRED_SECTIONS + 1))
    p.write_text(f"{body}\n\n~~~text\n{fence}\n~~~\n")
    return (f"{REQUIRED_SECTIONS} ## headings inside a ~~~ fence and no real sections")


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
        "log(`billing-ghost`)\n", encoding="utf-8")
    # exactly the name inside backticks: the prose fallback matches this shape,
    # so removing the workflow exclusion makes the case stop firing. A longer
    # sentence would not have matched the fallback either way, and the case
    # would have passed without depending on the implementation at all.
    return "an agent named only inside a template literal in a workflow"


def hl_orphan_commented_call(h: Path) -> str:
    """A commented-out call in a workflow is not a call.

    Matching the raw text kept an agent "referenced" by a line someone disabled
    months ago — found by fault injection, not by reading the code.
    """
    ghost = h / ".claude" / "agents" / "billing-ghost.md"
    ghost.write_text((h / ".claude" / "agents" / "billing-analyst.md").read_text()
                     .replace("billing-analyst", "billing-ghost"))
    wf = h / ".claude" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "nightly.ts").write_text(
        "export const meta = { name: 'nightly', description: 'x' }\n"
        "// agentType: 'billing-ghost'  <- disabled months ago\n", encoding="utf-8")
    return "an agent kept alive only by a commented-out call"


def hl_dead_api_in_workflow(h: Path) -> str:
    """A removed API called from a workflow script.

    `orphan-agents` learned to read workflows and `dead-api` did not, so this
    came back clean while the call sat in the main v2 execution path.
    """
    wf = h / ".claude" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "nightly.ts").write_text(
        "export const meta = { name: 'nightly', description: 'x' }\n"
        "TeamCreate({ team_name: 'billing' })\n", encoding="utf-8")
    return "a workflow calling the removed TeamCreate API"


def _ghost_plus_skill_line(h: Path, line: str) -> None:
    """An agent nothing calls, plus one line in the orchestrator that names it."""
    ghost = h / ".claude" / "agents" / "billing-ghost.md"
    ghost.write_text((h / ".claude" / "agents" / "billing-analyst.md").read_text()
                     .replace("billing-analyst", "billing-ghost"))
    skill = h / ".claude" / "skills" / "build" / "SKILL.md"
    with skill.open("a", encoding="utf-8") as fh:
        fh.write(line)


def hl_orphan_table_backtick(h: Path) -> str:
    """A row in a documentation table is not wiring in this runtime."""
    _ghost_plus_skill_line(h, "\n| `billing-ghost` | reviews the totals |\n")
    return "an agent named only by a backtick in a table"


def hl_orphan_at_mention(h: Path) -> str:
    _ghost_plus_skill_line(h, "\nHand the result to @billing-ghost when the sweep ends.\n")
    return "an agent named only by an @mention"


def hl_orphan_agent_key(h: Path) -> str:
    _ghost_plus_skill_line(h, '\nExample config: `agent: "billing-ghost"`\n')
    return 'an agent named only by a bare agent: "name" example'


def hl_orphan_bare_subagent_type(h: Path) -> str:
    """The call's argument, sitting outside any call."""
    _ghost_plus_skill_line(h, '\n| argument | `subagent_type: "billing-ghost"` |\n')
    return "an agent named only by subagent_type outside any Agent(...) call"


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
    "orphan-agents-commented-call": hl_orphan_commented_call,
    "dead-api-workflow": hl_dead_api_in_workflow,
    "orphan-agents-table-backtick": hl_orphan_table_backtick,
    "orphan-agents-at-mention": hl_orphan_at_mention,
    "orphan-agents-agent-key": hl_orphan_agent_key,
    "orphan-agents-bare-subagent-type": hl_orphan_bare_subagent_type,
}

# case name -> the rule it actually exercises, for the cases that are extra
# carriers rather than gates of their own
LINT_ALIASES = {
    "agent-sections-tilde-fence": "agent-sections",
    "dead-api-multiline-call": "dead-api",
    "orphan-agents-workflow-ghost": "orphan-agents",
    "orphan-agents-template-literal": "orphan-agents",
    "orphan-agents-commented-call": "orphan-agents",
    "dead-api-workflow": "dead-api",
    "orphan-agents-table-backtick": "orphan-agents",
    "orphan-agents-at-mention": "orphan-agents",
    "orphan-agents-agent-key": "orphan-agents",
    "orphan-agents-bare-subagent-type": "orphan-agents",
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

# preflight 를 재귀 없이 돌리기 위한 표시. `ci-runs-preflight` 가 CI 의 실행 단계에서
# 이 이름을 금지한다 — 아래 강제 확인을 끄는 스위치이기 때문이다.
NEST_ENV = "OH_MY_HARNESS_GUARDRAIL_NEST"

# (무엇을 깨뜨리나, 파일, 앵커, 대체) — 각각 «그 단계만» 잡는 결함이다.
PREFLIGHT_ENFORCEMENT = [
    ("the guardrail's judge",
     "guardrail self-test",
     "tests/guardrail/run_guardrail.py",
     '    if result.returncode == 0:\n        return "did NOT fail"\n',
     '    return None\n    if result.returncode == 0:\n        return "did NOT fail"\n'),
    ("the validator's _invokes",
     "validator self-test",
     "scripts/validate_repository.py",
     "    parts = re.split(",
     "    return script in command\n    parts = re.split("),
]


def guardrail_preflight_enforces(failures: list[str], verbose: bool) -> None:
    """Prove preflight.sh *enforces* — by running the real script on a broken tree.

    Pinning the runner's source text catches the tamper already seen; it does
    not catch the next one. Three more got through it in one sitting, each
    keeping the call line and the stage count intact:

      · a second `run()` definition overriding the canonical first
      · a shell function named `python3` shadowing the interpreter
      · `exit 0` where `exit $fail` belongs

    So ask the question directly instead of by proxy. Break a judge that only
    one stage can catch, run `bash scripts/preflight.sh`, and require a
    non-zero exit. Whatever route the neutering takes, the answer is the same.

    The pristine half needs no separate run: this suite *is* a preflight stage,
    so a green outer preflight already proves the clean tree passes.
    """
    if os.environ.get(NEST_ENV):
        print("  --  preflight enforcement: skipped (already inside a preflight run)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        for i, (label, stage, relpath, anchor, replacement) in enumerate(PREFLIGHT_ENFORCEMENT):
            broken = Path(tmp) / f"enforce-{i}"
            copy_tree(broken)
            target = broken / relpath
            text = target.read_text(encoding="utf-8")
            if anchor not in text:
                failures.append(f"preflight enforcement: the anchor for {label} is gone — "
                                f"this case would prove nothing")
                continue
            target.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
            # a mutation that does not parse is a syntax error, not a verdict
            syn = subprocess.run([sys.executable, "-m", "py_compile", str(target)],
                                 capture_output=True, text=True)
            if syn.returncode != 0:
                failures.append(f"preflight enforcement: breaking {label} left the file "
                                f"unparseable — {syn.stderr.strip().splitlines()[-1][:100]}")
                continue
            res = subprocess.run(["bash", "scripts/preflight.sh"], cwd=broken,
                                 capture_output=True, text=True,
                                 env=dict(os.environ, **{NEST_ENV: "1"}))
            if res.returncode == 0:
                failures.append(
                    f"preflight enforcement: {label} was broken and "
                    f"`bash scripts/preflight.sh` still exited 0 — the script counts "
                    f"its stages but does not enforce them")
                if verbose:
                    print(res.stdout[-2000:])
                continue
            # 빨간불이 «그 단계» 에서 나왔는지까지 본다. 아무 데서나 빨개진 것을
            # 증거로 세면 무관한 실패가 이 케이스를 영원히 통과시킨다.
            chunks = ("\n" + res.stdout).split("\n== ")
            chunk = next((c for c in chunks if c.startswith(stage)), None)
            if chunk is None:
                failures.append(f"preflight enforcement: the '{stage}' stage never ran "
                                f"while {label} was broken")
            elif "FAIL" not in chunk.upper():
                failures.append(f"preflight enforcement: preflight went red with {label} "
                                f"broken, but the '{stage}' stage passed — the red came "
                                f"from somewhere else and proves nothing")
            else:
                print(f"  ok  preflight enforces:    '{stage}' goes red when "
                      f"{label} is broken")


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
        ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__",
                                      ".omc", ".omx"),
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
    ALIASES = {"dead-api-yaml": "dead-api",
               "ci-preflight-comment-only": "ci-runs-preflight",
               "readme-rule-docs": "lint-rule-docs",
               "readme-rule-name": "lint-rule-docs",
               "preflight-stage-swapped": "preflight-stages",
               "preflight-run-tampered": "preflight-stages",
               "preflight-exit-code": "preflight-stages",
               "guardrail-section-removed": "preflight-stages",
               "preflight-exit-before": "preflight-stages",
               "preflight-function-keyword": "preflight-stages",
               "enforcement-emptied": "preflight-stages",
               "ci-nest-job-env": "ci-runs-preflight",
               "dead-api-duplicate-line": "dead-api",
               "preflight-runner-duplicate": "preflight-stages",
               "preflight-runner-shadow": "preflight-stages",
               "ci-integrity-step": "ci-runs-preflight",
               "ci-nest-switch": "ci-runs-preflight",
               "dead-api-stale-allowlist": "dead-api",
               "dead-api-build-dir": "dead-api",
               "ci-preflight-echo-only": "ci-runs-preflight",
               "ci-preflight-shell-comment": "ci-runs-preflight"}
    uncovered = sorted(set(known) - set(CASES) - set(ALIASES.values()))
    if uncovered:
        print(f"FAIL: checks with no guardrail case: {', '.join(uncovered)}", file=sys.stderr)
        return 1

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        pristine = Path(tmp) / "pristine"
        copy_tree(pristine)
        clean_by_gate: dict[str, subprocess.CompletedProcess] = {}

        for check, breaker in CASES.items():
            # 1. the pristine tree must pass, or the case proves nothing
            gate = ALIASES.get(check, check)
            if gate not in clean_by_gate:
                clean_by_gate[gate] = run_check(pristine, gate)
            clean = clean_by_gate[gate]
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
    guardrail_preflight_enforces(failures, args.verbose)

    if failures:
        print("\nGuardrail suite failed:", file=sys.stderr)
        for f in failures:
            print(f"- {f}", file=sys.stderr)
        return 1

    repo_rules = len({ALIASES.get(c, c) for c in CASES})
    lint_rules = len({LINT_ALIASES.get(c, c) for c in LINT_CASES})
    print(f"\nGuardrail suite passed: {repo_rules} repository rules "
          f"({len(CASES)} cases) + {lint_rules} harness-lint rules "
          f"({len(LINT_CASES)} cases) proven to fire on broken input, "
          f"{len(VALID_VARIANTS)} legitimate variants proven to pass, and "
          f"preflight.sh proven to go red for {len(PREFLIGHT_ENFORCEMENT)} "
          f"neutered judges")
    return 0


if __name__ == "__main__":
    sys.exit(main())
