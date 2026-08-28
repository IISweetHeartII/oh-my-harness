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
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent

# Paths excluded from the repository-wide scans. The guardrail fixtures are
# deliberately broken; scanning them would make the main run always fail.
# `.omc/` is the agent runtime's scratch directory. An advisor transcript landed
# there once and its quoted code examples tripped `dead-api` and `change-notice` —
# the gates were right about the text and wrong about the file being ours.
# Operational scratch is not repository content.
EXCLUDED_PARTS = {".git", "node_modules", ".omc", ".omx"}
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
# 제거된 API 의 고유 식별자. 대소문자를 무시한다 — 이 이름들은 Claude Code 고유라
# 다른 뜻으로 쓰일 여지가 없다.
DEAD_API_TOKENS = ["TeamCreate", "TeamDelete", "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"]
# `team_name` 은 평범한 인자명이다(스포츠·조직 관리 도메인). Claude 문맥이 같은 줄에
# 있을 때만 대상으로 삼는다 — 단독으로 잡으면 정상 하네스를 거부한다.
DEAD_API_CONTEXTUAL = {"team_name": ("TeamCreate", "TeamDelete", "Agent(", "subagent_type")}
DEAD_API_ALLOWLIST = ROOT / "docs" / "dead-api-allowlist.json"

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


# Directories and files Claude Code discovers by convention. Naming them again
# in plugin.json loads them twice, and the plugin then fails to load outright.
# `claude plugin validate` does not catch this — it checks manifest shape, not
# load semantics — so the first sign is an installed plugin that will not start.
CONVENTIONAL_PATHS = {
    "hooks": "./hooks/hooks.json",
    "commands": "./commands/",
    "skills": "./skills/",
    "agents": "./agents/",
}


def check_manifest_conventions(errors: list[str]) -> None:
    plugin = load_json(ROOT / ".claude-plugin" / "plugin.json", errors)
    if not plugin:
        return
    for field, conventional in CONVENTIONAL_PATHS.items():
        value = plugin.get(field)
        if isinstance(value, str) and value.rstrip("/") == conventional.rstrip("/"):
            errors.append(
                f"plugin.json declares {field!r} = {value!r}, which Claude Code already "
                f"discovers by convention. Declaring it again loads the same file twice "
                f"and the plugin fails to load. Remove the field, or point it at a "
                f"non-standard location.")


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


def first_party_text_files() -> list[Path]:
    """Every file this repository owns and that is readable as text.

    Scanning by extension meant `.sh`, `.py`, `.json` and `.ts` were invisible,
    so a removed API could sit in a code comment and the gate reported clean.
    Ownership is the honest boundary: what git tracks plus what is new and not
    ignored, minus what we did not write (vendor, build output) and runtime
    scratch. Binary files drop out by failing to decode.
    """
    out: list[Path] = []
    for args in (["git", "ls-files", "-z"],
                 ["git", "ls-files", "-z", "--others", "--exclude-standard"]):
        res = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
        for name in res.stdout.split("\0"):
            if not name:
                continue
            path = ROOT / name
            if not path.is_file():
                continue
            parts = path.relative_to(ROOT).parts
            if any(part in EXCLUDED_PARTS for part in parts):
                continue
            # vendor/dist/build 는 «최상위» 일 때만 남의 것이다. 경로 조각 어디에나
            # 적용했더니 `docs/build/` 가 통째로 스캔 밖이었다 — 우리가 쓰는 문서다.
            # 이름이 아니라 위치가 경계다.
            if parts[0] in {"vendor", "dist", "build"}:
                continue
            out.append(path)
    return sorted(set(out))


def _line_key(line: str) -> str:
    """Identify an occurrence by its content, not its line number.

    A line number moves when anything above it is edited, so an exemption keyed
    on it would silently start covering a different line. Keyed on the text, an
    edit makes the exemption stale — which is the correct outcome: the reason
    was written about the old wording.
    """
    return hashlib.sha256(re.sub(r"\s+", " ", line).strip().encode("utf-8")).hexdigest()[:16]


def dead_api_hits(path: Path) -> list[tuple[int, str, str]]:
    """(lineno, token, line) for every removed-API occurrence in one file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []                      # binary or unreadable: not first-party text
    found = []
    for lineno, line in enumerate(text.splitlines(), 1):
        lowered = line.lower()
        for token in DEAD_API_TOKENS:
            if token.lower() in lowered:
                found.append((lineno, token, line))
        for token, context in DEAD_API_CONTEXTUAL.items():
            if token in line and any(c in line for c in context):
                found.append((lineno, token, line))
    return found


def check_dead_api(errors: list[str]) -> None:
    """No removed-API identifier appears unless that occurrence is justified.

    The rule used to try to tell an instruction from a description, using a list
    of negation words. That is a meaning question and a word list does not close
    it: `TeamCreate was the original coordination API.` was rejected as an
    instruction, while `teamcreate()` passed because the match was
    case-sensitive. Whole-file exemptions made it worse — three files were
    exempt regardless of what they later grew to contain.

    So the rule no longer guesses. Every occurrence fails unless the allowlist
    justifies *that occurrence*, keyed by path + token + the line's own hash.
    Change the line and the exemption goes stale, because the reason was written
    about the old wording.
    """
    allow: dict[str, dict] = {}
    if DEAD_API_ALLOWLIST.is_file():
        raw = load_json(DEAD_API_ALLOWLIST, errors)
        if raw is None:
            return
        for entry in raw.get("allow", []):
            allow[f"{entry['path']}|{entry['token']}|{entry['sha']}"] = entry

    owned = first_party_text_files()
    if not owned:
        # git 이 아무것도 못 돌려주면 «전부 깨끗하다» 가 아니라 «무엇이 우리 것인지
        # 모른다» 다. 0개를 스캔하고 통과하면 최악의 경우가 가장 조용해진다.
        errors.append("cannot determine which files this repository owns "
                      "(git ls-files returned nothing) — the scan did not run")
        return

    seen: set[str] = set()
    for path in owned:
        # 장부 자신은 면제 대상을 «이름으로» 적어야 하므로 토큰을 담을 수밖에 없다.
        # 이건 판단이 아니라 구조다 — 다른 파일과 달리 대안이 없다.
        if path == DEAD_API_ALLOWLIST:
            continue
        for lineno, token, line in dead_api_hits(path):
            key = f"{rel(path)}|{token}|{_line_key(line)}"
            entry = allow.get(key)
            if entry is None:
                errors.append(
                    f"{rel(path)}:{lineno} contains removed API {token} with no justification. "
                    f"Delete it, or add to {rel(DEAD_API_ALLOWLIST)}: "
                    f'{{"path": "{rel(path)}", "token": "{token}", '
                    f'"sha": "{_line_key(line)}", "reason": "<why this line must exist>"}}'
                )
                continue
            seen.add(key)
            if not str(entry.get("reason", "")).strip() or "TODO" in str(entry.get("reason")):
                errors.append(f"{rel(path)}:{lineno} is allowlisted for {token} "
                              f"with no real reason — write why this line must exist")

    # An exemption whose line is gone or reworded is stale. Leaving it in place
    # would quietly pre-approve whatever text lands on that key next.
    for key, entry in allow.items():
        if key not in seen:
            errors.append(
                f"{rel(DEAD_API_ALLOWLIST)} still exempts {entry['token']} in "
                f"{entry['path']} (sha {entry['sha']}), but that line no longer exists "
                f"as written — remove the entry or re-justify the new wording"
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


# preflight 가 «반드시 실행해야 하는» 것들. 개수 세기(preflight 안)와 이 목록(밖)이
# 서로를 받친다 — 하나를 지우면 개수가 어긋나고, 다른 것으로 바꿔치기하면 이 목록이 잡는다.
REQUIRED_PREFLIGHT_CALLS = [
    ("tests/guardrail/run_guardrail.py", "--self-test"),   # 판정기 자신을 먼저 시험
    ("scripts/validate_repository.py", None),              # 저장소 게이트
    ("tests/guardrail/run_guardrail.py", None),            # 가드레일 스위트
    ("scripts/harness_lint.py", None),                     # 참조 하네스
    ("scripts/validate_repository.py", "--self-test"),     # 판정 함수 자신
]

# preflight 의 «실행기» 는 글자 그대로 이 모양이어야 한다.
#
# 왜 (2026-08-28 실측): 호출 줄도 STAGES_EXPECTED 도 그대로 둔 채 run() 만
# 「--self-test 이면 그냥 return 0」 으로 고쳤더니, 그 단계가 한 번도 안 돌았는데
# preflight-stages 도 preflight 도 초록이었다. 게이트가 «호출 줄» 을 보고 있었지
# «실행» 을 보고 있지 않았다. 스크립트는 자기 자신에 대한 편집을 막을 수 없으니
# 판정은 바깥 파일이 한다.
PREFLIGHT_RUNNER_BODIES = {
    "run": r"""run() { printf '\n== %s\n' "$1"; shift; stages_run=$((stages_run + 1)); "$@" || fail=1; }""",
    "stage": r"""stage() { printf '\n== %s\n' "$1"; stages_run=$((stages_run + 1)); }""",
}


def _preflight_commands() -> list[str]:
    """The commands preflight.sh actually executes.

    `run "label" cmd args...` lines, not the whole file — a mention in a comment
    is not an invocation. Same mistake as the CI gate, one level in.
    """
    text = (ROOT / "scripts" / "preflight.sh").read_text(encoding="utf-8")
    out = []
    for line in text.splitlines():
        m = re.match(r'^\s*run\s+"[^"]*"\s+(.*)$', line)
        if m:
            out.append(_strip_shell_comments(m.group(1)).strip())
    return [c for c in out if c]


def check_preflight_stages(errors: list[str]) -> None:
    """Every gate this repository owns is actually invoked by preflight.sh.

    Removing the self-test line and breaking the judge produced exit 0 — the
    gates existed, and the line that ran one of them did not. A check nobody
    calls is not a check, and nothing was watching the calls.
    """
    commands = _preflight_commands()
    if not commands:
        errors.append("scripts/preflight.sh has no `run \"...\" <command>` stages")
        return
    for script, flag in REQUIRED_PREFLIGHT_CALLS:
        matches = [c for c in commands if _invokes(c, script)]
        if flag is not None:
            matches = [c for c in matches if flag in c.split()]
        if not matches:
            want = f"{script} {flag}" if flag else script
            errors.append(f"scripts/preflight.sh never runs {want} — "
                          f"that gate exists but nothing calls it")
    # 개수 선언이 실제 단계 수와 맞는지도 본다 — 선언만 고치고 단계를 지우는 우회를 막는다
    text = (ROOT / "scripts" / "preflight.sh").read_text(encoding="utf-8")
    m = re.search(r"^STAGES_EXPECTED=(\d+)", text, re.M)
    if not m:
        errors.append("scripts/preflight.sh no longer declares STAGES_EXPECTED")
    else:
        declared = int(m.group(1))
        actual = len(commands) + len(re.findall(r'^\s*stage\s+"', text, re.M))
        if declared != actual:
            errors.append(f"scripts/preflight.sh declares STAGES_EXPECTED={declared} "
                          f"but has {actual} stages")
    # 그리고 실행기 자체 — 호출 줄과 개수를 그대로 둔 채 run() 만 고치면
    # 「센 단계」와 「실행한 단계」가 갈라진다.
    for name, want in PREFLIGHT_RUNNER_BODIES.items():
        got = next((l.strip() for l in text.splitlines()
                    if l.strip().startswith(f"{name}() ")), None)
        if got is None:
            errors.append(f"scripts/preflight.sh no longer defines {name}()")
        elif got != want:
            errors.append(
                f"scripts/preflight.sh's {name}() is not the canonical runner — "
                f"a stage can be counted without being executed. "
                f"want: {want}  ||  got: {got}")


# 셸에서 스크립트가 «실행되는» 형태. `echo X` 는 X 를 출력할 뿐 실행하지 않는다.
# basename 으로 비교한다 — `/bin/bash` 도 bash 다.
SHELL_RUNNERS = {
    "bash", "sh", "zsh", "source", ".", "exec", "command", "time", "sudo", "env",
    # 인터프리터도 실행자다. 이걸 빼놨더니 `python3 scripts/x.py` 를 «실행 아님» 으로
    # 읽어, 멀쩡한 preflight 를 「아무것도 안 부른다」고 보고했다 — 거짓양성 넷.
    "python", "python3", "node", "deno", "bun", "ruby", "perl", "uv", "uvx", "npx",
}

# 실행자에 붙으면 «실행이 아니게» 되는 단문자 옵션. (실행자, 글자) 쌍이다 —
# `bash -n x.sh` 는 문법만 보고, `command -v x.sh` 는 경로만 찾는다.
# 긴 옵션(`--norc`)은 글자 포함으로 판정하면 안 되므로 아예 보지 않는다.
NON_EXECUTING_FLAGS = {("bash", "n"), ("sh", "n"), ("zsh", "n"),
                       ("command", "v"), ("command", "V")}

# 값을 하나 더 먹는 옵션. 이걸 모르면 `sudo -u root bash x.sh` 의 `root` 가
# 스크립트 자리로 보여, 실제로 실행하는 명령을 «실행 아님» 으로 읽는다.
FLAGS_WITH_VALUE = {"-u", "-g", "-C", "-p", "-U", "-r", "-t", "--user", "--group"}
ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")


def _norm_path(token: str) -> str:
    token = token.strip("'\"")
    while token.startswith("./"):
        token = token[2:]
    return token


def _same_script(token: str, script: str) -> bool:
    """The argv slot names this script — by relative path or with a prefix."""
    want, got = _norm_path(script), _norm_path(token)
    return got == want or got.endswith("/" + want)


def _statement_invokes(stmt: str, script: str) -> bool:
    """Does this one command put `script` in the argv slot that gets executed?"""
    try:
        toks = shlex.split(stmt, comments=True)
    except ValueError:
        toks = stmt.split()          # unbalanced quotes: fall back to whitespace
    i = 0
    while i < len(toks):
        tok = toks[i]
        if ASSIGNMENT_RE.fullmatch(tok):
            i += 1                    # leading VAR=value
            continue
        runner = os.path.basename(_norm_path(tok))
        if runner not in SHELL_RUNNERS:
            break
        i += 1
        while i < len(toks) and toks[i].startswith("-") and toks[i] != "--":
            opt = toks[i]
            if not opt.startswith("--"):
                letters = set(opt[1:])
                if any(runner == r and f in letters for r, f in NON_EXECUTING_FLAGS):
                    return False
            i += 1
            if opt in FLAGS_WITH_VALUE and i < len(toks) and not toks[i].startswith("-"):
                i += 1
        if i < len(toks) and toks[i] == "--":
            i += 1
    return i < len(toks) and _same_script(toks[i], script)


def _invokes(command: str, script: str) -> bool:
    """Is `script` actually executed by this shell snippet, not merely named?

    `run: echo scripts/preflight.sh` mentions it and runs nothing. Deciding
    that with `script in command` is the substring mistake yet again — the
    question is a position in the command, not a presence in the string.

    Being wrong in the other direction is just as bad and happened too: the
    first positional version rejected `/bin/bash scripts/preflight.sh` and
    `sudo -u root bash scripts/preflight.sh`, so a working CI read as broken.
    `--self-test` pins both directions.
    """
    parts = re.split(r"(\n|;|&&|\|\||\|)", command)
    dead = False                      # inside a branch that cannot run
    for idx in range(0, len(parts), 2):
        if not dead and _statement_invokes(parts[idx], script):
            return True
        sep = parts[idx + 1] if idx + 1 < len(parts) else None
        prev = parts[idx].strip()
        if sep == "&&":
            dead = dead or prev in {"false", "/bin/false"}
        elif sep == "||":
            dead = prev in {"true", ":", "/bin/true"}
        else:
            dead = False
    return False


def _strip_shell_comments(body: str) -> str:
    """Drop `#` comments from a shell snippet.

    `run: # bash scripts/preflight.sh` executes nothing, and a comment-only
    block scalar executes nothing either — both satisfied the gate. Reading a
    run step as one string is the same substring mistake one level in.
    """
    out = []
    for line in body.splitlines():
        stripped = re.sub(r'(?:^|(?<=\s))#.*$', "", line)
        if stripped.strip():
            out.append(stripped)
    return "\n".join(out)


def _workflow_run_commands(text: str) -> list[str]:
    """The shell commands a GitHub workflow actually executes.

    Only `run:` step bodies, including block scalars. Reading the whole file as
    one string counts the header comment — which is how a workflow that ran
    `echo validation-skipped` passed a gate whose whole job was to check that it
    runs preflight. A comment is not an execution step.
    """
    lines, out, i = text.splitlines(), [], 0
    while i < len(lines):
        m = re.match(r"^(\s*)-?\s*run:\s*(.*)$", lines[i])
        if not m:
            i += 1
            continue
        indent, rest = len(m.group(1)), m.group(2).strip()
        if rest and rest[0] not in "|>":
            out.append(_strip_shell_comments(rest))
            i += 1
            continue
        # a block scalar: everything indented deeper than the `run:` key
        i += 1
        block = []
        while i < len(lines):
            line = lines[i]
            if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                break
            block.append(line)
            i += 1
        out.append(_strip_shell_comments("\n".join(block)))
    return out


def check_ci_runs_preflight(errors: list[str]) -> None:
    """CI must run the same script a human runs, not its own copy of the list.

    v2.7.0 shipped with a failing guardrail because the push command ran one
    gate out of three. preflight.sh exists to stop that — but only while the
    thing that actually blocks a merge calls it. A workflow that re-lists the
    gates is the same bug one level up: the two lists drift, and the green tick
    starts meaning "the gates CI knows about".
    """
    wf = ROOT / ".github" / "workflows" / "validation.yml"
    if not wf.is_file():
        errors.append(".github/workflows/validation.yml is missing")
        return
    commands = _workflow_run_commands(wf.read_text(encoding="utf-8"))
    commands = [c for c in commands if c.strip()]
    if not commands:
        errors.append("validation.yml has no run: step that executes anything")
        return
    if not any(_invokes(c, "scripts/preflight.sh") for c in commands):
        errors.append("no run: step in validation.yml executes scripts/preflight.sh — "
                      "CI and the local gate can now disagree "
                      f"(steps found: {'; '.join(c.splitlines()[0][:60] for c in commands)})")
    for script in ("scripts/validate_repository.py", "tests/guardrail/run_guardrail.py"):
        # naming a gate directly is how the lists drift apart again — but
        # «naming» is not «running», so ask the same positional question.
        if any(_invokes(c, script) for c in commands):
            errors.append(f"a run: step calls {script} directly instead of going "
                          f"through scripts/preflight.sh")


def check_lint_rule_docs(errors: list[str]) -> None:
    """Every implemented lint rule is named in the docs, and the counts agree.

    The linter grew from seven rules to nine and two of the docs kept saying
    seven — including the fallback list a user follows when the plugin is not
    installed, which therefore told them to skip two checks. Documentation
    that describes a checker is part of the checker.
    """
    listed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "harness_lint.py"), "--list"],
        capture_output=True, text=True, check=False,
    ).stdout.split()
    if not listed:
        errors.append("could not read the rule list from harness_lint.py --list")
        return
    # The READMEs describe the same rules to the people deciding whether to
    # install this. They said seven rules and four sections while nine and five
    # were implemented, and this gate did not look at them — it checked the two
    # documents it was written against and reported clean.
    required_sections = int(re.search(
        r"^REQUIRED_AGENT_SECTION_COUNT\s*=\s*(\d+)",
        (ROOT / "scripts" / "harness_lint.py").read_text(encoding="utf-8"), re.M).group(1))
    for readme in sorted(ROOT.glob("README*.md")):
        text = readme.read_text(encoding="utf-8")
        missing = [r for r in listed if f"`{r}`" not in text]
        if missing:
            errors.append(f"{rel(readme)} never names these implemented rules: "
                          f"{', '.join(missing)}")
        lines = text.splitlines()
        first_rule = next((n for n, l in enumerate(lines) if "`agent-naming`" in l), None)
        if first_rule is None:
            errors.append(f"{rel(readme)} has no rule table to check")
        else:
            intro = next((lines[n] for n in range(first_rule - 1, -1, -1)
                          if lines[n].strip() and not lines[n].lstrip().startswith("|")), "")
            counts = {int(n) for n in re.findall(r"(?<!\d)(\d+)(?!\d)", intro)}
            if counts != {len(listed)}:
                errors.append(
                    f"{rel(readme)} introduces the rule table with {sorted(counts) or 'no number'}; "
                    f"harness_lint implements {len(listed)} rules")
        row = next((l for l in text.splitlines() if "`agent-sections`" in l), None)
        if row is None:
            errors.append(f"{rel(readme)} has no `agent-sections` row to check")
        else:
            # the row states how many contract sections are required; whatever
            # language it is written in, the number has to be the real one
            # `\b` does not fire between a digit and a CJK character, so `5개`
            # read as "no number at all". A check that is wrong in one language
            # is a false positive waiting to switch the check off.
            numbers = {int(n) for n in re.findall(r"(?<!\d)(\d+)(?!\d)", row)}
            if numbers != {required_sections}:
                errors.append(
                    f"{rel(readme)}'s agent-sections row states {sorted(numbers) or 'no'} "
                    f"section(s); harness_lint requires {required_sections}")

    for doc in ("skills/harness/SKILL.md", "commands/harness-lint.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        missing = [r for r in listed if f"`{r}`" not in text]
        # the command file describes the rules by count, not by name
        if doc.endswith("commands/harness-lint.md"):
            if f"{len(listed)}종" not in text:
                errors.append(f"{doc} does not say 검사 {len(listed)}종 — "
                              f"harness_lint.py implements {len(listed)} rules")
            continue
        if missing:
            errors.append(f"{doc} never names these implemented rules: {', '.join(missing)}")
        if f"위 {len(listed)}개 항목" not in text:
            errors.append(f"{doc}'s manual fallback does not say 위 {len(listed)}개 항목 — "
                          f"it would tell a plugin-less user to skip rules")


CHECKS = {
    "required-files": check_required_files,
    "size-budget": check_size_budget,
    "fixtures-tracked": check_fixtures_tracked,
    "readme-parity": check_readme_parity,
    "plugin-manifests": check_plugin_manifests,
    "manifest-conventions": check_manifest_conventions,
    "skill-frontmatter": check_skill_frontmatter,
    "link-existence": check_link_existence,
    "dead-api": check_dead_api,
    "version-consistency": check_version_consistency,
    "change-notice": check_change_notice,
    "lint-rule-docs": check_lint_rule_docs,
    "ci-runs-preflight": check_ci_runs_preflight,
    "preflight-stages": check_preflight_stages,
}


# (셸 조각, 스크립트, 이것이 «실행» 인가) — 양방향 둘 다 적는다.
# 한쪽만 재면 규칙이 틀린 채로 완벽하게 발화한다.
INVOKES_SELF_TEST = [
    ("bash scripts/preflight.sh", "scripts/preflight.sh", True),
    ("/bin/bash scripts/preflight.sh", "scripts/preflight.sh", True),
    ("./scripts/preflight.sh", "scripts/preflight.sh", True),
    ('bash "scripts/preflight.sh"', "scripts/preflight.sh", True),
    ("bash --norc scripts/preflight.sh", "scripts/preflight.sh", True),
    ("sudo -u root bash scripts/preflight.sh", "scripts/preflight.sh", True),
    ("env -i HOME=/tmp bash scripts/preflight.sh", "scripts/preflight.sh", True),
    ("set -e\nbash scripts/preflight.sh", "scripts/preflight.sh", True),
    ("python3 scripts/validate_repository.py --self-test",
     "scripts/validate_repository.py", True),
    ("echo scripts/preflight.sh", "scripts/preflight.sh", False),
    ("cat scripts/preflight.sh", "scripts/preflight.sh", False),
    ("ls -l scripts/preflight.sh", "scripts/preflight.sh", False),
    ("bash -n scripts/preflight.sh", "scripts/preflight.sh", False),
    ("command -v scripts/preflight.sh", "scripts/preflight.sh", False),
    ("false && bash scripts/preflight.sh || true", "scripts/preflight.sh", False),
    ("true || bash scripts/preflight.sh", "scripts/preflight.sh", False),
    ("echo 'nightly runs scripts/preflight.sh'", "scripts/preflight.sh", False),
]


def self_test() -> int:
    """Test this file's judging function, in both directions.

    `_invokes` decides whether CI really runs the gate, and it has been wrong
    each way: it passed `echo scripts/preflight.sh` (named, never run) and it
    rejected `/bin/bash scripts/preflight.sh` (run, not recognised). One
    direction hides a dead CI; the other trains you to ignore the gate. Only
    the pair is evidence.
    """
    fail = 0
    for snippet, script, want in INVOKES_SELF_TEST:
        got = _invokes(snippet, script)
        if got == want:
            print(f"  ok  _invokes({snippet!r}) = {got}")
        else:
            print(f"FAIL _invokes({snippet!r}) = {got}, want {want}", file=sys.stderr)
            fail = 1
    print("self-test passed" if not fail else "self-test FAILED")
    return fail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        action="append",
        choices=sorted(CHECKS),
        help="run only the named check (repeatable); default runs all",
    )
    parser.add_argument("--list", action="store_true", help="list check names and exit")
    parser.add_argument("--self-test", action="store_true",
                        help="test this file's own judging functions and exit")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    if args.list:
        for name in sorted(CHECKS):
            print(name)
        return 0

    selected = args.only or sorted(CHECKS)
    errors: list[str] = []
    for name in selected:
        # 각 검사의 finding 에 그 검사의 이름을 붙인다. 이름이 없으면 「무엇이
        # 잡았는지」를 밖에서 확인할 수 없고, 가드레일이 «규칙이 발화했다» 와
        # «검사기가 어떤 이유로든 죽었다» 를 구분하지 못한다.
        before = len(errors)
        CHECKS[name](errors)
        for i in range(before, len(errors)):
            errors[i] = f"[{name}] {errors[i]}"

    if errors:
        print("Repository validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Repository validation passed ({len(selected)} checks: {', '.join(selected)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
