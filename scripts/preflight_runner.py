#!/usr/bin/env python3
"""Run every gate this repository owns, in one place, and report one result.

Why this is Python and not shell (2026-08-28, after ten reviews):

The shell version declared its stages as `run "label" cmd` lines and the
repository gate tried to prove, by reading that file, that the stages were
really executed. Ten rounds of review broke that proof six times — a second
`run()` definition, a shell function named `python3`, `exit 0` above the
stages, `fail=0` after them, an EXIT trap, a `\\`-continued redefinition — and
the eleventh (`eval 'run() { ...; }'`) showed the shape of the problem: the set
of ways shell can redefine or short-circuit something is not a list you can
finish writing. Every fix was another entry in a blacklist.

Here the stages are data. The count is `len(STAGES)`, not a number kept in
step by hand. There is one place that decides the exit code. `preflight.sh` is
two lines that exec this file, and the gate pins those two lines exactly — so
there is no shell left to subvert.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def stage_nothing_to_lint() -> bool:
    """Linting a directory with no harness is "nothing to measure" (2), not clean."""
    with tempfile.TemporaryDirectory() as empty:
        rc = subprocess.run([PY, "scripts/harness_lint.py", empty],
                            cwd=ROOT, capture_output=True).returncode
    if rc == 2:
        print("  ok  exit 2")
        return True
    print(f"  FAIL exit {rc}")
    return False


def stage_json_parses() -> bool:
    bad = []
    for path in sorted(ROOT.rglob("*.json")):
        if any(p in {".git", "node_modules", ".omc", ".omx"} for p in path.parts):
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            bad.append(f"{path.relative_to(ROOT)}: {exc}")
    if bad:
        print("Invalid JSON:\n" + "\n".join(bad))
        return False
    print("  ok  all JSON files parse")
    return True


def stage_no_conflict_markers() -> bool:
    # '=======' alone is also a Markdown setext underline. Only count it when the
    # same file carries an opening or closing marker — prose never pairs them.
    OPEN, MID, CLOSE = "<<<<<<< ", "=======", ">>>>>>> "
    SUFFIXES = {".md", ".json", ".yml", ".yaml", ".py", ".sh"}
    offenders = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        if any(p in {".git", "node_modules", ".omc", ".omx"} for p in path.parts):
            continue
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        bracketed = any(l.startswith(OPEN) or l.startswith(CLOSE) for l in lines)
        for n, line in enumerate(lines, 1):
            if line.startswith(OPEN) or line.startswith(CLOSE) or (
                    bracketed and line.rstrip() == MID):
                offenders.append(f"{path.relative_to(ROOT)}:{n}:{line}")
    if offenders:
        print("Merge conflict markers found:\n" + "\n".join(offenders))
        return False
    print("  ok  no merge conflict markers")
    return True


# (label, argv or callable). The label is what the guardrail's enforcement
# section looks for when it checks that a *specific* stage went red, so these
# strings are part of the contract.
#
# The judges come first: if `verdict()` or this file's own parsing is wrong,
# every "ok" below it is worth nothing.
STAGES = [
    ("guardrail self-test", [PY, "tests/guardrail/run_guardrail.py", "--self-test"]),
    ("validator self-test", [PY, "scripts/validate_repository.py", "--self-test"]),
    ("repository gates", [PY, "scripts/validate_repository.py"]),
    ("guardrail suite", [PY, "tests/guardrail/run_guardrail.py"]),
    ("reference harness", [PY, "scripts/harness_lint.py", "tests/fixtures/clean-harness"]),
    ("nothing-to-lint returns 2, not 0", stage_nothing_to_lint),
    ("every JSON parses", stage_json_parses),
    ("no merge conflict markers", stage_no_conflict_markers),
]


def main() -> int:
    failed = []
    for label, action in STAGES:
        print(f"\n== {label}", flush=True)
        if callable(action):
            ok = action()
        else:
            ok = subprocess.run(action, cwd=ROOT).returncode == 0
        if not ok:
            failed.append(label)
    print()
    if failed:
        print(f"preflight: FAILED — do not push ({len(failed)}/{len(STAGES)} stages: "
              f"{', '.join(failed)})")
        return 1
    print(f"preflight: all gates green ({len(STAGES)} stages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
