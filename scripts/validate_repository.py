#!/usr/bin/env python3
"""Validate the oh-my-harness repository's publishable plugin and skill assets.

Modified from revfactory/harness (Apache-2.0, Copyright 2025 robin).
Upstream shipped the required-files / manifest / skill-reference / link-warning
checks; this version turns broken links into errors and adds the dead-api,
version-consistency, skill-frontmatter and change-notice gates.

This deliberately avoids strict Markdown style linting. The repository has a
large amount of long-form/localized Markdown, so this gate focuses on trust
checks that are stable and non-invasive for incoming PRs.

Every check is selectable with --only so the guardrail suite can prove each
gate actually fails on a deliberately broken fixture. A gate nobody has seen
fail is not a gate.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent

# Paths excluded from the repository-wide scans. The guardrail fixtures are
# deliberately broken; scanning them would make the main run always fail.
EXCLUDED_PARTS = {".git", "node_modules"}
# The whole tests/ tree holds deliberately broken fixtures. Scanning it would
# make the main run fail on files whose entire purpose is to be wrong.
TESTS_DIR = ROOT / "tests"
GUARDRAIL_DIR = TESTS_DIR / "guardrail"

REQUIRED_FILES = [
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "skills/harness/SKILL.md",
    "LICENSE",
    "NOTICE",
]

REQUIRED_PLUGIN_FIELDS = [
    "name",
    "description",
    "version",
    "author",
    "homepage",
    "repository",
    "license",
]

REFERENCE_RE = re.compile(r"`(references/[^`\n]+)`")
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
CHANGELOG_RELEASE_RE = re.compile(r"^##\s*\[(\d+\.\d+\.\d+)\]", re.MULTILINE)

# APIs removed from Claude Code 2.1.178. Referencing them as an instruction
# silently produces a harness that does not do what its own docs claim, because
# a missing tool makes the model improvise rather than error.
DEAD_API_TOKENS = ["TeamCreate", "TeamDelete", "team_name", "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"]
# A line that says the API is gone is documentation, not an instruction.
DEAD_API_NEGATIONS = [
    "removed", "remove", "no longer", "does not exist", "deprecated", "legacy",
    "gone", "dropped", "drop", "delete", "deleted",
    "제거", "없다", "없습니다", "존재하지 않", "삭제", "소멸", "금지", "잔재", "v1",
    "削除", "存在しません", "排除", "禁止", "不要",
]
# Whole files whose subject *is* the removed API. A migration guide has to name
# what it migrates away from, and a changelog has to say what it removed.
# Keeping these out of the scan is what keeps the gate's false-positive rate at
# zero — a check that cries wolf gets switched off.
DEAD_API_EXEMPT_FILES = {
    "docs/migration-v1-to-v2.md",
    "CHANGELOG.md",
    "docs/ATTRIBUTION.md",
}

CHANGE_NOTICE_MARKERS = ("Modified from revfactory/harness", "Apache-2.0")
DERIVED_MANIFEST = ROOT / "docs" / "derived-files.json"

# Context efficiency is the product: a skill that does not fit comfortably in a
# window stops being loaded in full. Budgets from upstream PR #41 (@mythkiven).
SKILL_MAX_LINES = 520
REFERENCE_MAX_LINES = 650


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_json(path: Path, errors: list[str]) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{rel(path)} is invalid JSON: {exc}")
    except OSError as exc:
        errors.append(f"{rel(path)} cannot be read: {exc}")
    return {}


def scanned_markdown() -> list[Path]:
    return _scanned(("*.md",))


def scanned_text() -> list[Path]:
    """Markdown plus the YAML that also instructs a reader.

    dead-api originally scanned only Markdown, and the inherited issue
    templates therefore kept telling people to export a flag that no longer
    exists. Filtering by extension is how a check quietly stops covering the
    thing it was written for.
    """
    return _scanned(("*.md", "*.yml", "*.yaml"))


def _scanned(patterns: tuple[str, ...]) -> list[Path]:
    out = []
    for pattern in patterns:
        for path in ROOT.rglob(pattern):
            if any(part in EXCLUDED_PARTS for part in path.parts):
                continue
            if TESTS_DIR in path.parents or path.parent == TESTS_DIR:
                continue
            out.append(path)
    return sorted(set(out))


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

def check_required_files(errors: list[str]) -> None:
    for name in REQUIRED_FILES:
        if not (ROOT / name).is_file():
            errors.append(f"missing required file: {name}")


def check_plugin_manifests(errors: list[str]) -> None:
    plugin_path = ROOT / ".claude-plugin" / "plugin.json"
    marketplace_path = ROOT / ".claude-plugin" / "marketplace.json"
    if not plugin_path.is_file() or not marketplace_path.is_file():
        return

    plugin = load_json(plugin_path, errors)
    marketplace = load_json(marketplace_path, errors)
    if not plugin or not marketplace:
        return

    for field in REQUIRED_PLUGIN_FIELDS:
        if not plugin.get(field):
            errors.append(f"plugin.json missing required field: {field}")

    name = plugin.get("name")
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        errors.append("marketplace.json must contain at least one plugin entry")
        return

    entries = [e for e in plugins if e.get("name") == name]
    if not entries:
        errors.append(f"marketplace.json missing plugin entry named {name!r}")
        return

    entry = entries[0]
    if entry.get("version") != plugin.get("version"):
        errors.append(
            f"marketplace entry version {entry.get('version')!r} does not match "
            f"plugin.json version {plugin.get('version')!r}"
        )
    if entry.get("source") != "./":
        errors.append("marketplace plugin source must be './'")


def check_skill_frontmatter(errors: list[str]) -> None:
    skills_dir = ROOT / "skills"
    if not skills_dir.is_dir():
        errors.append("missing skills/ directory")
        return

    found = False
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        found = True
        name_expected = skill_md.parent.name
        text = skill_md.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            errors.append(f"{rel(skill_md)} missing YAML frontmatter")
            continue
        end = text.find("\n---", 4)
        if end == -1:
            errors.append(f"{rel(skill_md)} frontmatter is not closed")
            continue
        frontmatter = text[4:end]
        for field in ("name:", "description:"):
            if field not in frontmatter:
                errors.append(f"{rel(skill_md)} frontmatter missing {field}")
        m = re.search(r"^name:\s*['\"]?([A-Za-z0-9_-]+)", frontmatter, re.MULTILINE)
        if m and m.group(1) != name_expected:
            errors.append(
                f"{rel(skill_md)} frontmatter name {m.group(1)!r} does not match "
                f"its directory {name_expected!r}"
            )
        for ref in REFERENCE_RE.findall(text):
            if not (skill_md.parent / ref).is_file():
                errors.append(f"{rel(skill_md)} has a broken reference path: {ref}")

    if not found:
        errors.append("no skills/*/SKILL.md found")


def _skip_link(raw_url: str) -> bool:
    raw_url = raw_url.strip()
    if not raw_url or raw_url.startswith("#"):
        return True
    parsed = urlparse(raw_url)
    return bool(parsed.scheme or parsed.netloc)


def check_link_existence(errors: list[str]) -> None:
    """Broken local links are errors, not warnings.

    Upstream reported these as warnings. A warning next to a green check mark
    reads as 'fine', which is how four non-existent docs stayed referenced for
    months.
    """
    for md in scanned_markdown():
        text = md.read_text(encoding="utf-8")
        for raw_url in MARKDOWN_LINK_RE.findall(text):
            if _skip_link(raw_url):
                continue
            clean = unquote(raw_url.split("#", 1)[0].split("?", 1)[0]).strip()
            if not clean:
                continue
            target = (md.parent / clean).resolve()
            try:
                target.relative_to(ROOT.resolve())
            except ValueError:
                continue
            if not target.exists():
                errors.append(f"{rel(md)} links to a missing local path: {raw_url}")


def check_dead_api(errors: list[str]) -> None:
    """Flag removed-API tokens used as instructions rather than as history."""
    for md in scanned_text():
        if rel(md) in DEAD_API_EXEMPT_FILES:
            continue
        for lineno, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
            hits = [t for t in DEAD_API_TOKENS if t in line]
            if not hits:
                continue
            lowered = line.lower()
            if any(neg.lower() in lowered for neg in DEAD_API_NEGATIONS):
                continue
            errors.append(
                f"{rel(md)}:{lineno} references removed API {', '.join(hits)} "
                f"as an instruction (add the removal context, or delete the line)"
            )


def check_version_consistency(errors: list[str]) -> None:
    plugin = load_json(ROOT / ".claude-plugin" / "plugin.json", errors)
    marketplace = load_json(ROOT / ".claude-plugin" / "marketplace.json", errors)
    changelog = ROOT / "CHANGELOG.md"
    if not plugin or not marketplace or not changelog.is_file():
        return

    plugin_version = plugin.get("version")
    releases = CHANGELOG_RELEASE_RE.findall(changelog.read_text(encoding="utf-8"))
    if not releases:
        errors.append("CHANGELOG.md has no '## [x.y.z]' release heading")
        return

    if releases[0] != plugin_version:
        errors.append(
            f"CHANGELOG.md latest release [{releases[0]}] does not match "
            f"plugin.json version {plugin_version!r}"
        )

    entries = [e for e in marketplace.get("plugins", []) if e.get("name") == plugin.get("name")]
    if entries and entries[0].get("version") != plugin_version:
        errors.append("marketplace.json version does not match plugin.json version")


def _cross_check_manifest_against_git(
    manifest: dict, modified: set[str], errors: list[str]
) -> None:
    """Compare the declared 'modified' set against git, when git can answer.

    Silently skips when git, the repository, or the baseline commit is absent —
    the manifest is the authority in those environments, and a check that errors
    out on a tarball would just get disabled.
    """
    message = manifest.get("baselineCommitMessage")
    if not message:
        return
    try:
        found = subprocess.run(
            ["git", "log", "--format=%H", "--fixed-strings", f"--grep={message}", "--all"],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        )
        if found.returncode != 0 or not found.stdout.strip():
            return
        baseline = found.stdout.split()[-1]
        # Compare the baseline against the WORKING TREE, not against HEAD. A
        # baseline..HEAD diff only sees committed changes, so an uncommitted
        # edit to a file declared 'unmodified' would slip through — which is
        # exactly the hole this cross-check exists to close.
        diff = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=M", baseline],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        )
        if diff.returncode != 0:
            return
    except (OSError, subprocess.SubprocessError):
        return

    actual = {line for line in diff.stdout.splitlines() if line}
    for path_str in sorted(actual - modified):
        errors.append(
            f"{path_str} differs from the upstream baseline but docs/derived-files.json "
            f"does not list it under 'modified'"
        )
    for path_str in sorted(modified - actual):
        errors.append(
            f"docs/derived-files.json lists {path_str} as modified, but it is identical "
            f"to the upstream baseline"
        )


def check_change_notice(errors: list[str]) -> None:
    """Apache-2.0 section 4(b): modified files must carry a change notice.

    docs/derived-files.json records which paths came from upstream and which of
    those we modified. Both directions are checked, so a file cannot quietly
    drop its notice and a file we wrote ourselves cannot falsely claim one.
    """
    if not DERIVED_MANIFEST.is_file():
        errors.append("missing docs/derived-files.json (change-notice manifest)")
        return

    manifest = load_json(DERIVED_MANIFEST, errors)
    if not manifest:
        return

    modified = set(manifest.get("modified", []))
    unmodified = set(manifest.get("unmodified", []))
    comment_free = set(manifest.get("commentUnsupported", []))
    # Files we authored that nonetheless carry upstream-licensed contributions
    # (an adopted pull request). Not in the baseline tree, but still derivative.
    derived_new = set(manifest.get("derivedNew", []))

    for path_str in sorted(modified | unmodified | comment_free | derived_new):
        if not (ROOT / path_str).is_file():
            errors.append(f"docs/derived-files.json lists a missing path: {path_str}")

    for path_str in sorted((modified | derived_new) - comment_free):
        path = ROOT / path_str
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if not all(marker in text for marker in CHANGE_NOTICE_MARKERS):
            errors.append(
                f"{path_str} is a modified upstream file but carries no change notice "
                f"(needs {' + '.join(CHANGE_NOTICE_MARKERS)})"
            )

    for path_str in sorted(comment_free):
        if path_str not in modified:
            continue
        notice = ROOT / "NOTICE"
        if notice.is_file() and path_str not in notice.read_text(encoding="utf-8"):
            errors.append(
                f"{path_str} cannot carry an inline comment, so NOTICE must list it"
            )

    # The manifest is hand-maintained so the gate still works where .git does not
    # exist (tarball, shallow clone, plugin cache). That leaves one hole: editing
    # a file listed as unmodified without updating the manifest. Where git IS
    # available, close it by comparing against the baseline commit.
    _cross_check_manifest_against_git(manifest, modified, errors)

    # A file we authored must not claim upstream lineage it does not have.
    declared = modified | unmodified | comment_free | derived_new
    for md in scanned_markdown():
        path_str = rel(md)
        if path_str in declared:
            continue
        if CHANGE_NOTICE_MARKERS[0] in md.read_text(encoding="utf-8"):
            errors.append(
                f"{path_str} carries an upstream change notice but is not listed "
                f"in docs/derived-files.json"
            )


def check_readme_parity(errors: list[str]) -> None:
    """Keep the translated READMEs structurally in step with the English one.

    Upstream dropped its Japanese README with the reason "maintenance cost
    versus low utility", and that reason was sound: a translation nobody can
    tell has gone stale is worse than no translation. This repository keeps
    three languages, so it owes a way to notice the drift. Comparing the
    version badge and the set of section headings is coarse, but it is
    countable, and a countable check is one that stays switched on.
    """
    base = ROOT / "README.md"
    if not base.is_file():
        return

    def shape(path: Path) -> tuple[str, int]:
        text = path.read_text(encoding="utf-8")
        badge = re.search(r"badge/Version-([0-9.]+)-", text)
        headings = re.findall(r"^## ", text, re.MULTILINE)
        return (badge.group(1) if badge else "", len(headings))

    want_version, want_sections = shape(base)
    for path in sorted(ROOT.glob("README_*.md")):
        got_version, got_sections = shape(path)
        if got_version != want_version:
            errors.append(
                f"{rel(path)} version badge {got_version!r} does not match "
                f"README.md {want_version!r}"
            )
        if got_sections != want_sections:
            errors.append(
                f"{rel(path)} has {got_sections} top-level sections but README.md "
                f"has {want_sections} — the translation has drifted"
            )


def check_fixtures_tracked(errors: list[str]) -> None:
    """Files the test suite depends on must actually be in the repository.

    The reference harness lives under a .claude/ directory, and the blanket
    `.claude/` line in .gitignore swallowed it whole. Locally everything passed
    because the files were on disk; CI cloned a repository where they did not
    exist. "Works on my machine" here was literally "the file is on my machine".
    """
    fixture = ROOT / "tests" / "fixtures" / "clean-harness"
    if not fixture.is_dir():
        errors.append("tests/fixtures/clean-harness is missing")
        return
    on_disk = {p.relative_to(ROOT).as_posix() for p in fixture.rglob("*") if p.is_file()}
    if not on_disk:
        errors.append("tests/fixtures/clean-harness has no files")
        return
    try:
        listed = subprocess.run(["git", "ls-files", "tests/fixtures"],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        if listed.returncode != 0:
            return  # not a git checkout; the manifest is the authority here
    except (OSError, subprocess.SubprocessError):
        return
    tracked = {line for line in listed.stdout.splitlines() if line}
    for path_str in sorted(on_disk - tracked):
        errors.append(
            f"{path_str} exists on disk but git does not track it — "
            f"CI will run without it (check .gitignore)")


def check_size_budget(errors: list[str]) -> None:
    for skill_md in sorted((ROOT / "skills").glob("*/SKILL.md")):
        n = len(skill_md.read_text(encoding="utf-8").splitlines())
        if n > SKILL_MAX_LINES:
            errors.append(f"{rel(skill_md)} is {n} lines (budget {SKILL_MAX_LINES})")
    for ref in sorted((ROOT / "skills").glob("*/references/*.md")):
        n = len(ref.read_text(encoding="utf-8").splitlines())
        if n > REFERENCE_MAX_LINES:
            errors.append(f"{rel(ref)} is {n} lines (budget {REFERENCE_MAX_LINES})")


CHECKS = {
    "required-files": check_required_files,
    "size-budget": check_size_budget,
    "fixtures-tracked": check_fixtures_tracked,
    "readme-parity": check_readme_parity,
    "plugin-manifests": check_plugin_manifests,
    "skill-frontmatter": check_skill_frontmatter,
    "link-existence": check_link_existence,
    "dead-api": check_dead_api,
    "version-consistency": check_version_consistency,
    "change-notice": check_change_notice,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        action="append",
        choices=sorted(CHECKS),
        help="run only the named check (repeatable); default runs all",
    )
    parser.add_argument("--list", action="store_true", help="list check names and exit")
    args = parser.parse_args()

    if args.list:
        for name in sorted(CHECKS):
            print(name)
        return 0

    selected = args.only or sorted(CHECKS)
    errors: list[str] = []
    for name in selected:
        CHECKS[name](errors)

    if errors:
        print("Repository validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Repository validation passed ({len(selected)} checks: {', '.join(selected)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
