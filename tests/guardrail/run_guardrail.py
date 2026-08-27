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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = Path("scripts/validate_repository.py")
CASES_DIR = Path(__file__).resolve().parent / "cases"


# --------------------------------------------------------------------------
# breakages — each takes the temp repo root and makes exactly one thing wrong
# --------------------------------------------------------------------------

def break_required_files(repo: Path) -> str:
    (repo / "NOTICE").unlink()
    return "deleted NOTICE"


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


def break_size_budget(repo: Path) -> str:
    path = repo / "skills" / "harness" / "SKILL.md"
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n" + "\n".join(f"padding line {i}" for i in range(600)) + "\n")
    return "padded skills/harness/SKILL.md past its line budget"


CASES = {
    "required-files": break_required_files,
    "size-budget": break_size_budget,
    "plugin-manifests": break_plugin_manifests,
    "skill-frontmatter": break_skill_frontmatter,
    "link-existence": break_link_existence,
    "dead-api": break_dead_api,
    "version-consistency": break_version_consistency,
    "change-notice": break_change_notice,
}


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    known = subprocess.run(
        [sys.executable, str(VALIDATOR), "--list"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.split()
    uncovered = sorted(set(known) - set(CASES))
    if uncovered:
        print(f"FAIL: checks with no guardrail case: {', '.join(uncovered)}", file=sys.stderr)
        return 1

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        pristine = Path(tmp) / "pristine"
        copy_tree(pristine)

        for check, breaker in CASES.items():
            # 1. the pristine tree must pass, or the case proves nothing
            clean = run_check(pristine, check)
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

            result = run_check(broken, check)
            if result.returncode == 0:
                failures.append(f"{check}: did NOT fail after {what}")
            else:
                print(f"  ok  {check:22s} caught: {what}")
                if args.verbose:
                    print("      " + result.stderr.strip().replace("\n", "\n      "))
            shutil.rmtree(broken)

    if failures:
        print("\nGuardrail suite failed:", file=sys.stderr)
        for f in failures:
            print(f"- {f}", file=sys.stderr)
        return 1

    print(f"\nGuardrail suite passed: {len(CASES)} checks each proven to fail on a broken tree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
