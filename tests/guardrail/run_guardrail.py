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


def break_enforcement_emptied(repo: Path) -> str:
    """The enforcement section still runs, with nothing left to measure."""
    p = repo / "tests" / "guardrail" / "run_guardrail.py"
    text = p.read_text(encoding="utf-8")
    start = text.index("PREFLIGHT_ENFORCEMENT = [")
    end = text.index("\n]\n", start) + len("\n]\n")
    p.write_text(text[:start] + "PREFLIGHT_ENFORCEMENT = [\n]\n" + text[end:],
                 encoding="utf-8")
    return "an emptied enforcement list — the section runs and proves nothing"


def break_preflight_wrapper(repo: Path) -> str:
    """Put shell back into the wrapper.

    The whole point of the two-line wrapper is that there is no shell left to
    subvert. One extra effective line reopens that door, so the gate pins the
    file's effective lines exactly rather than trying to interpret them.
    """
    p = repo / "scripts" / "preflight.sh"
    text = p.read_text(encoding="utf-8")
    marker = "exec python3"
    if marker not in text:
        raise AssertionError("preflight.sh no longer execs the runner")
    p.write_text(text.replace(marker, "python3() { return 0; }\nexec python3", 1),
                 encoding="utf-8")
    return "shell put back into the wrapper that exists to have none"


def break_stage_removed(repo: Path) -> str:
    """Delete the stage that runs the judge's self-test."""
    p = repo / "scripts" / "preflight_runner.py"
    text = p.read_text(encoding="utf-8")
    line = ('    ("guardrail self-test", [PY, "tests/guardrail/run_guardrail.py", '
            '"--self-test"]),\n')
    if line not in text:
        raise AssertionError("the runner no longer declares the self-test stage this way")
    p.write_text(text.replace(line, "", 1), encoding="utf-8")
    return "the stage that runs the judge's self-test deleted from STAGES"


def break_stage_swapped(repo: Path) -> str:
    """Keep the stage and its label; point it at something harmless."""
    p = repo / "scripts" / "preflight_runner.py"
    text = p.read_text(encoding="utf-8")
    old = '[PY, "tests/guardrail/run_guardrail.py", "--self-test"]'
    if old not in text:
        raise AssertionError("the runner no longer declares the self-test stage this way")
    p.write_text(text.replace(old, '[PY, "-c", "pass"]', 1), encoding="utf-8")
    return "a stage kept in the list but pointed at a no-op"


def break_stage_callable_dropped(repo: Path) -> str:
    """Drop a Python stage from the list while its function stays behind."""
    p = repo / "scripts" / "preflight_runner.py"
    text = p.read_text(encoding="utf-8")
    line = '    ("every JSON parses", stage_json_parses),\n'
    if line not in text:
        raise AssertionError("the runner no longer declares the JSON stage this way")
    p.write_text(text.replace(line, "", 1), encoding="utf-8")
    return "a Python stage removed from STAGES while its function remains"


def break_runner_main_gutted(repo: Path) -> str:
    """`main()` prints the labels and runs nothing.

    STAGES is untouched, the summary still says "all gates green", and no
    gate runs. Reading the declaration is not reading the program — this is
    the one the eleventh review found, with every static check passing.
    """
    p = repo / "scripts" / "preflight_runner.py"
    text = p.read_text(encoding="utf-8")
    start = text.index("def main() -> int:")
    p.write_text(text[:start] + (
        "def main() -> int:\n"
        "    for label, _action in STAGES:\n"
        '        print(f"\\n== {label}", flush=True)\n'
        "    print()\n"
        '    print(f"preflight: all gates green ({len(STAGES)} stages)")\n'
        "    return 0\n\n\n"
        'if __name__ == "__main__":\n'
        "    sys.exit(main())\n"), encoding="utf-8")
    return "a main() that announces every stage and executes none"


def break_runner_stages_mutated(repo: Path) -> str:
    """Replace every action with a no-op after STAGES is declared.

    The labels still print in order, so comparing declared labels against the
    run's headers cannot see it. The declaration has to be the list that runs.
    """
    p = repo / "scripts" / "preflight_runner.py"
    text = p.read_text(encoding="utf-8")
    anchor = "def main() -> int:"
    if anchor not in text:
        raise AssertionError("the runner has no main() to insert before")
    p.write_text(text.replace(
        anchor, "STAGES[:] = [(label, lambda: True) for label, _ in STAGES]\n\n\n"
                + anchor, 1), encoding="utf-8")
    return "every stage action swapped for a no-op after the declaration"


def break_runner_argv_head(repo: Path) -> str:
    """Point a stage's argv at something other than the interpreter."""
    p = repo / "scripts" / "preflight_runner.py"
    text = p.read_text(encoding="utf-8")
    old = '[PY, "tests/guardrail/run_guardrail.py", "--self-test"]'
    if old not in text:
        raise AssertionError("the runner no longer declares the self-test stage this way")
    p.write_text(text.replace("PY = sys.executable",
                              'PY = sys.executable\nNOOP = "true"', 1)
                 .replace(old, '[NOOP, "tests/guardrail/run_guardrail.py", "--self-test"]',
                          1), encoding="utf-8")
    return "a stage whose argv starts with something that is not the interpreter"


def break_ci_step_replaced_by_decoy(repo: Path) -> str:
    """Real steps replaced by `echo`, canonical lines hidden in a job-level env.

    Counting occurrences is not enough when the decoy *replaces* the real line
    instead of joining it: each required line still appears exactly once, in
    order. The line has to be at step position.
    """
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    marker = "    runs-on: ubuntu-latest\n"
    integrity = "        run: python3 scripts/validate_repository.py --only preflight-stages\n"
    preflight = "        run: bash scripts/preflight.sh\n"
    for needed in (marker, integrity, preflight):
        if needed not in text:
            raise AssertionError("validation.yml is not the shape this case rewrites")
    text = text.replace(integrity, "        run: echo integrity skipped\n", 1)
    text = text.replace(preflight, "        run: echo preflight skipped\n", 1)
    text = text.replace(marker, marker + "    env:\n      NOTES: |\n"
                        + integrity + preflight, 1)
    wf.write_text(text, encoding="utf-8")
    return "the real steps replaced by echo, the canonical lines moved into env"


def break_ci_job_disabled(repo: Path) -> str:
    """`if: ${{ false }}` on the job — every required line stays, nothing runs."""
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    marker = "    runs-on: ubuntu-latest\n"
    if marker not in text:
        raise AssertionError("validation.yml no longer declares runs-on the expected way")
    wf.write_text(text.replace(marker, marker + "    if: ${{ false }}\n", 1),
                  encoding="utf-8")
    return "the whole job switched off by a condition, every line still in place"


def break_runner_selective(repo: Path) -> str:
    """Announce every stage, execute only the one a single-defect probe watched.

    This is why the probe plants defects in several stages and requires the
    untouched ones to come back green: with one defect, this runner reproduced
    the expected answer while seven gates never ran.
    """
    p = repo / "scripts" / "preflight_runner.py"
    text = p.read_text(encoding="utf-8")
    anchor = '        print(f"\\n== {label}", flush=True)\n'
    if anchor not in text:
        raise AssertionError("the runner no longer announces stages this way")
    p.write_text(text.replace(
        anchor, anchor + '        if label != "guardrail self-test":\n'
                         "            continue\n", 1), encoding="utf-8")
    return "a runner that executes only the stage a probe was expected to watch"


def break_ci_yaml_fake_step(repo: Path) -> str:
    """The required lines inside a job `name:` block, the real steps echoing.

    Text-position reading called this a step. A YAML parser calls it a string.
    """
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    integrity = "        run: python3 scripts/validate_repository.py --only preflight-stages\n"
    preflight = "        run: bash scripts/preflight.sh\n"
    marker = "    runs-on: ubuntu-latest\n"
    for needed in (integrity, preflight, marker):
        if needed not in text:
            raise AssertionError("validation.yml is not the shape this case rewrites")
    text = text.replace(integrity, "        run: echo integrity skipped\n", 1)
    text = text.replace(preflight, "        run: echo preflight skipped\n", 1)
    text = text.replace(marker, "    name: |2\n      - name: gate\n" + integrity
                        + "      - name: gate2\n" + preflight + marker, 1)
    wf.write_text(text, encoding="utf-8")
    return "the gate commands parked inside a job name, the real steps echoing"


def break_ci_branch_filter(repo: Path) -> str:
    """Keep both triggers and point them at a branch that does not exist."""
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    old = "on:\n  pull_request:\n  push:\n    branches:\n      - main\n"
    if old not in text:
        raise AssertionError("validation.yml no longer declares its triggers this way")
    wf.write_text(text.replace(
        old, "on:\n  pull_request:\n    branches:\n      - never-run-this\n"
             "  push:\n    branches:\n      - never-run-this\n", 1), encoding="utf-8")
    return "both triggers restricted to a branch nothing ever pushes"


def break_ci_probe_switch(repo: Path) -> str:
    """CI setting the probe's own signal — the behavioural check turns off."""
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    marker = "    runs-on: ubuntu-latest\n"
    if marker not in text:
        raise AssertionError("validation.yml no longer declares runs-on the expected way")
    wf.write_text(text.replace(
        marker, marker + '    env:\n      OH_MY_HARNESS_PROBE: "1"\n', 1),
        encoding="utf-8")
    return "CI switching off the probe that proves preflight enforces its gates"


def break_runner_dead_code(repo: Path) -> str:
    """A main() carrying every marker a shape check looked for, inside `if False`.

    The loop, the `action()` call, the `subprocess.run`, the `return 1` are all
    present in the source and none of them execute. This is why the shape rules
    were replaced by running the thing.
    """
    p = repo / "scripts" / "preflight_runner.py"
    text = p.read_text(encoding="utf-8")
    start = text.index("def main() -> int:")
    p.write_text(text[:start] + (
        "def main() -> int:\n"
        "    failed = []\n"
        "    for label, action in STAGES:\n"
        '        print(f"\\n== {label}", flush=True)\n'
        "    if False:\n"
        "        action()\n"
        "        subprocess.run(action, cwd=ROOT)\n"
        "        return 1\n"
        '    print(f"\\npreflight: all gates green ({len(STAGES)} stages)")\n'
        "    return 0\n\n\n"
        'if __name__ == "__main__":\n'
        "    sys.exit(main())\n"), encoding="utf-8")
    return "a main() whose every stage call sits in dead code"


def break_runner_alias_mutation(repo: Path) -> str:
    """Empty STAGES through an alias — the name `STAGES` is never touched."""
    p = repo / "scripts" / "preflight_runner.py"
    text = p.read_text(encoding="utf-8")
    marker = "def main() -> int:"
    if marker not in text:
        raise AssertionError("the runner has no main() to insert before")
    p.write_text(text.replace(
        marker, "ALIAS = STAGES\nALIAS[:] = [(label, lambda: True) for label, _ in ALIAS]"
                "\n\n\n" + marker, 1), encoding="utf-8")
    return "every stage neutered through an alias, leaving STAGES untouched"


def break_preflight_unicode_break(repo: Path) -> str:
    """A U+0085 where a newline is expected.

    Python's `splitlines()` treats it as a line break and bash does not, so the
    exec stayed inside the comment while the gate saw two clean lines.
    """
    p = repo / "scripts" / "preflight.sh"
    text = p.read_text(encoding="utf-8")
    marker = "# 설치형 pre-push 훅: bash scripts/install-hooks.sh\n"
    if marker not in text:
        raise AssertionError("preflight.sh no longer ends its comments this way")
    p.write_text(text.replace(marker, marker.rstrip("\n") + "\u0085", 1), encoding="utf-8")
    return "a Unicode line separator bash does not treat as one"


def break_ci_custom_shell(repo: Path) -> str:
    """`defaults.run.shell: true {0}` — every run: step succeeds without running."""
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    marker = "    runs-on: ubuntu-latest\n"
    if marker not in text:
        raise AssertionError("validation.yml no longer declares runs-on the expected way")
    wf.write_text(text.replace(
        marker, marker + "    defaults:\n      run:\n        shell: true {0}\n", 1),
        encoding="utf-8")
    return "a custom shell that reports success without running the step"


def break_ci_quoted_if(repo: Path) -> str:
    """The same condition written as a quoted key with a space before the colon."""
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    marker = "    runs-on: ubuntu-latest\n"
    if marker not in text:
        raise AssertionError("validation.yml no longer declares runs-on the expected way")
    wf.write_text(text.replace(
        marker, marker + "    \"if\" : github.repository == 'someone/else'\n", 1),
        encoding="utf-8")
    return "the job condition written as a quoted key, spelled past a prefix check"


def break_ci_triggers_removed(repo: Path) -> str:
    """Leave only `workflow_dispatch` — no pull request or push ever runs it."""
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    old = "on:\n  pull_request:\n  push:\n    branches:\n      - main\n  workflow_dispatch:\n"
    if old not in text:
        raise AssertionError("validation.yml no longer declares its triggers this way")
    wf.write_text(text.replace(old, "on:\n  workflow_dispatch:\n", 1), encoding="utf-8")
    return "the automatic triggers removed, leaving a gate nothing starts"


def break_nest_marker_tracked(repo: Path) -> str:
    """A leftover `.guardrail-nested` from the old file-based signal.

    This used to be an environment variable, and a variable can be set from
    outside the file the gate reads: a composite action writing `$GITHUB_ENV`,
    a self-hosted runner's service environment, or a single `export` line
    inside preflight.sh itself. A tracked file cannot hide like that.
    """
    marker = repo / ".guardrail-nested"
    marker.write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "-f", ".guardrail-nested"], cwd=repo,
                   check=True, capture_output=True)
    return "the recursion marker committed into the repository"


def break_ci_preflight_action_input(repo: Path) -> str:
    """The command moved into an action's `with:` input — it never runs.

    A `run:` key is only a step when it is the step's own key. Read by name
    alone, an action input satisfied the required-step check while CI executed
    nothing.
    """
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    line = "        run: bash scripts/preflight.sh\n"
    if line not in text:
        raise AssertionError("validation.yml no longer runs preflight the way this case expects")
    wf.write_text(text.replace(
        line, "        uses: actions/github-script@v7\n        with:\n"
              "          run: bash scripts/preflight.sh\n", 1), encoding="utf-8")
    return "the gate command demoted to an action input that never executes"


def break_ci_preflight_swallowed(repo: Path) -> str:
    """CI runs the gate and throws its verdict away."""
    wf = repo / ".github" / "workflows" / "validation.yml"
    text = wf.read_text(encoding="utf-8")
    line = "        run: bash scripts/preflight.sh\n"
    if line not in text:
        raise AssertionError("validation.yml no longer runs preflight the way this case expects")
    wf.write_text(text.replace(line, "        run: bash scripts/preflight.sh || true\n", 1),
                  encoding="utf-8")
    return "CI swallowing preflight's exit code with `|| true`"


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
    "ci-runs-preflight": break_ci_runs_preflight,
    "ci-preflight-comment-only": break_ci_preflight_comment_only,
    "ci-preflight-echo-only": break_ci_preflight_echo,
    "dead-api-stale-allowlist": break_dead_api_stale_allowlist,
    "dead-api-build-dir": break_dead_api_build_dir,
    "ci-integrity-step": break_ci_integrity_step,
    "preflight-stages": break_preflight_wrapper,
    "preflight-stage-removed": break_stage_removed,
    "preflight-stage-swapped": break_stage_swapped,
    "preflight-stage-callable-dropped": break_stage_callable_dropped,
    "runner-main-gutted": break_runner_main_gutted,
    "runner-stages-mutated": break_runner_stages_mutated,
    "runner-argv-head": break_runner_argv_head,
    "ci-step-replaced-by-decoy": break_ci_step_replaced_by_decoy,
    "ci-job-disabled": break_ci_job_disabled,
    "runner-selective": break_runner_selective,
    "ci-yaml-fake-step": break_ci_yaml_fake_step,
    "ci-branch-filter": break_ci_branch_filter,
    "ci-probe-switch": break_ci_probe_switch,
    "runner-dead-code": break_runner_dead_code,
    "runner-alias-mutation": break_runner_alias_mutation,
    "preflight-unicode-break": break_preflight_unicode_break,
    "ci-custom-shell": break_ci_custom_shell,
    "ci-quoted-if": break_ci_quoted_if,
    "ci-triggers-removed": break_ci_triggers_removed,
    "nest-marker-tracked": break_nest_marker_tracked,
    "ci-preflight-swallowed": break_ci_preflight_swallowed,
    "ci-preflight-action-input": break_ci_preflight_action_input,
    "guardrail-section-removed": break_guardrail_section,
    "enforcement-emptied": break_enforcement_emptied,
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

# preflight 를 재귀 없이 돌리기 위한 표시. 사본 안에만 만드는 파일이다 —
# 환경변수는 워크플로우 밖에서도 켤 수 있어(composite action·`$GITHUB_ENV`·
# preflight 안의 export) 강제 확인을 조용히 끌 수 있었다. `preflight-stages` 가
# 이 파일이 저장소에 있으면 거부한다.
NEST_ENV = "OH_MY_HARNESS_PROBE"   # 파일이 아니라 환경변수 — 리뷰 13

# (무엇을 깨뜨리나, 파일, 앵커, 대체) — 각각 «그 단계만» 잡는 결함이다.
PREFLIGHT_ENFORCEMENT = [
    ("the guardrail's judge",
     "guardrail self-test",
     "tests/guardrail/run_guardrail.py",
     '    if result.returncode == 0:\n        return "did NOT fail"\n',
     '    return None\n    if result.returncode == 0:\n        return "did NOT fail"\n'),
    ("the validator's stage reader",
     "validator self-test",
     "scripts/validate_repository.py",
     "    tree = ast.parse(path.read_text(encoding=\"utf-8\"))\n",
     "    return [], [], 0\n"
     "    tree = ast.parse(path.read_text(encoding=\"utf-8\"))\n"),
]


def guardrail_allowlist_suggestion(failures: list[str], verbose: bool) -> None:
    """The exemption the gate prints must actually work when pasted back.

    Every other dead-api case proves the rule *fires*. None proved the way out
    of it is usable — and it was not: with two identical lines in one file the
    message printed the bare line hash, and pasting that entry verbatim left
    the second occurrence still failing. A gate whose suggested fix does not
    fix anything trains people to disable it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "suggestion"
        copy_tree(repo)
        allowlist = repo / "docs" / "dead-api-allowlist.json"
        data = json.loads(allowlist.read_text(encoding="utf-8"))
        entry = data["allow"][0]
        target = repo / entry["path"]
        lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
        hit = next((i for i, l in enumerate(lines) if entry["token"] in l), None)
        if hit is None:
            failures.append(f"allowlist suggestion: {entry['path']} no longer contains "
                            f"{entry['token']} — this case would prove nothing")
            return
        lines.insert(hit + 1, lines[hit])          # a second, identical occurrence
        target.write_text("".join(lines), encoding="utf-8")

        before = run_check(repo, "dead-api")
        if before.returncode != 1:
            failures.append("allowlist suggestion: duplicating an exempted line did not "
                            "produce a finding, so there is no suggestion to test")
            return
        m = re.search(r'(\{"path".*?\})', before.stderr)
        if not m:
            failures.append("allowlist suggestion: the message no longer prints a "
                            "ready-to-paste entry")
            return
        suggested = json.loads(m.group(1))
        suggested["reason"] = "guardrail: the duplicated line under test"
        data["allow"].append(suggested)
        allowlist.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")

        after = run_check(repo, "dead-api")
        if after.returncode != 0:
            failures.append("allowlist suggestion: pasting the printed entry verbatim "
                            f"still fails — {after.stderr.strip().splitlines()[-1][:120]}")
        else:
            print(f"  ok  allowlist suggestion: pasting the printed entry "
                  f"(sha {suggested['sha']}) resolves the finding")


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
    # 목록이 «있는지» 는 밖에서 세지만, 그 사이에 비워지는 길이 있다
    # (`PREFLIGHT_ENFORCEMENT.clear()` 한 줄이면 정적 검사는 통과한다 — 리뷰 9).
    # 여기서 다시 센다. 실행 시점의 값이 진실이다.
    if len(PREFLIGHT_ENFORCEMENT) < 2:
        failures.append(f"preflight enforcement: only {len(PREFLIGHT_ENFORCEMENT)} "
                        f"case(s) at run time — the section runs and proves nothing")
        return

    # 「선언된 단계가 실제로 돌았나」. 정적으로 STAGES 를 읽는 게이트와, 실행이
    # 실제로 낸 출력을 맞대 본다 — `STAGES.pop()` 처럼 선언 뒤에 목록을 바꾸면
    # 둘이 갈라지고, 그 갈라짐이 여기서만 보인다.
    with tempfile.TemporaryDirectory() as tmp:
        clean = Path(tmp) / "declared-vs-run"
        copy_tree(clean)
        res = subprocess.run(["bash", "scripts/preflight.sh"], cwd=clean,
                             capture_output=True, text=True,
                             env=dict(os.environ, **{NEST_ENV: "1"}))
        declared = [m.group(1) for m in re.finditer(
            r'^\s{4}\("([^"]+)",', (clean / "scripts" / "preflight_runner.py")
            .read_text(encoding="utf-8"), re.M)]
        ran = re.findall(r"^== (.+)$", res.stdout, re.M)
        if res.returncode != 0:
            failures.append("declared stages actually ran: the clean tree does not pass "
                            f"preflight — {res.stdout.strip().splitlines()[-1][:120]}")
        elif ran != declared:
            failures.append(f"declared stages actually ran: preflight_runner.py declares "
                            f"{declared} but the run produced {ran} — a stage is declared "
                            f"and not executed, or executed and not declared")
        else:
            print(f"  ok  declared stages actually ran: {len(ran)} declared, "
                  f"{len(ran)} executed, same order")
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
                                 capture_output=True, text=True,
                                 env=dict(os.environ, **{NEST_ENV: "1"}))
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

    # 프로브 안이다. 프로브가 재는 것은 «1단계가 실제로 돌았는가» 뿐이고, 이 스위트를
    # 한 번 더 도는 데 10초가 든다. 자기시험(--self-test)은 위에서 이미 지나갔으므로
    # 프로브가 보려는 것은 그대로 측정된다.
    if os.environ.get(NEST_ENV):
        print("guardrail suite: skipped (inside a preflight probe)")
        return 0

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
               "guardrail-section-removed": "preflight-stages",
               "enforcement-emptied": "preflight-stages",
               "dead-api-duplicate-line": "dead-api",
               "ci-integrity-step": "ci-runs-preflight",
               "preflight-stage-removed": "preflight-stages",
               "preflight-stage-swapped": "preflight-stages",
               "preflight-stage-callable-dropped": "preflight-stages",
               "runner-main-gutted": "preflight-stages",
               "runner-stages-mutated": "preflight-stages",
               "runner-argv-head": "preflight-stages",
               "ci-step-replaced-by-decoy": "ci-runs-preflight",
               "ci-job-disabled": "ci-runs-preflight",
               "runner-selective": "preflight-stages",
               "ci-yaml-fake-step": "ci-runs-preflight",
               "ci-branch-filter": "ci-runs-preflight",
               "ci-probe-switch": "ci-runs-preflight",
               "runner-dead-code": "preflight-stages",
               "runner-alias-mutation": "preflight-stages",
               "preflight-unicode-break": "preflight-stages",
               "ci-custom-shell": "ci-runs-preflight",
               "ci-quoted-if": "ci-runs-preflight",
               "ci-triggers-removed": "ci-runs-preflight",
               "nest-marker-tracked": "preflight-stages",
               "ci-preflight-swallowed": "ci-runs-preflight",
               "ci-preflight-action-input": "ci-runs-preflight",
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
    guardrail_allowlist_suggestion(failures, args.verbose)

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
