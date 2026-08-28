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
import ast
import hashlib
import json
import os
import re
import subprocess
import tempfile
import shutil
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
        # 추적되는 파일은 누군가 «넣기로 결정한» 것이다. 이름이 build 든 dist 든
        # 우리 것이다. 이름 기반 제외는 추적되지 않는 산출물에만 쓴다.
        tracked = "--others" not in args
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
            if not tracked and parts[0] in {"vendor", "dist", "build"}:
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
    ordinal: dict[str, int] = {}
    for path in owned:
        # 장부 자신은 면제 대상을 «이름으로» 적어야 하므로 토큰을 담을 수밖에 없다.
        # 이건 판단이 아니라 구조다 — 다른 파일과 달리 대안이 없다.
        if path == DEAD_API_ALLOWLIST:
            continue
        for lineno, token, line in dead_api_hits(path):
            # 같은 파일에 «글자까지 같은» 줄이 둘 있으면 키가 겹쳐, 하나를 승인하면
            # 나머지가 조용히 따라 들어왔다(리뷰 8 실측). 몇 번째인지도 키에 넣는다.
            base = f"{rel(path)}|{token}|{_line_key(line)}"
            ordinal[base] = ordinal.get(base, 0) + 1
            key = base if ordinal[base] == 1 else f"{base}#{ordinal[base]}"
            entry = allow.get(key)
            if entry is None:
                errors.append(
                    f"{rel(path)}:{lineno} contains removed API {token} with no justification. "
                    f"Delete it, or add to {rel(DEAD_API_ALLOWLIST)}: "
                    f'{{"path": "{rel(path)}", "token": "{token}", '
                    f'"sha": "{key.split("|", 2)[2]}", '
                    f'"reason": "<why this line must exist>"}}'
                    + ("  (the `#N` suffix marks which occurrence of an identical "
                       "line this is — without it the entry covers the first one)"
                       if "#" in key else "")
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
# 가드레일 스위트가 «반드시 부르는» 절. 한 줄을 지우면 그 절 전체가 조용히 사라진다 —
# 스위트 안에서는 아무도 모르고, 요약 문장만 짧아진다. 그래서 밖에서 센다.
REQUIRED_GUARDRAIL_SECTIONS = ("guardrail_harness_lint", "guardrail_valid_variants",
                               "guardrail_preflight_enforces",
                               "guardrail_allowlist_suggestion")

# preflight.sh 는 이제 «두 줄» 이다 — 러너를 exec 할 뿐이다. 주석을 뺀 유효 줄이
# 정확히 이것이어야 한다. 셸이 두 줄뿐이면 셸로 할 수 있는 우회도 두 줄만큼이다.
PREFLIGHT_WRAPPER_LINES = [
    "#!/usr/bin/env bash",
    'exec python3 "$(dirname "$0")/preflight_runner.py" "$@"',
]

# 러너가 «반드시» 돌려야 하는 것. argv 꼬리(인터프리터 뒤)로 비교한다.
REQUIRED_STAGE_COMMANDS = [
    ("tests/guardrail/run_guardrail.py", "--self-test"),
    ("scripts/validate_repository.py", "--self-test"),
    ("scripts/validate_repository.py",),
    ("tests/guardrail/run_guardrail.py",),
    ("scripts/harness_lint.py", "tests/fixtures/clean-harness"),
]
# 그리고 파이썬으로 쓰인 단계들. 이름이 사라지면 그 단계가 통째로 없어진 것이다.
REQUIRED_STAGE_CALLABLES = ("stage_nothing_to_lint", "stage_json_parses",
                            "stage_no_conflict_markers")

# CI 는 이 줄들을 «글자 그대로, 각각 한 번씩, 이 순서로» 가져야 한다.
# YAML 의미를 해석하지 않는다 — 우리가 쓴 파일의 줄을 고정할 뿐이다. 접는 스칼라
# 안에 같은 줄을 숨겨도 «두 번» 이 되어 걸린다.
# CI 가 «단계로서» 실행해야 하는 명령. 줄 위치가 아니라 YAML 구조로 찾는다.
CI_REQUIRED_STEP_RUNS = [
    "python3 scripts/validate_repository.py --only preflight-stages",
    "bash scripts/preflight.sh",
]
# 프로브 신호를 CI 가 켜면 프로브가 꺼진다. 이름이 워크플로우 어디에 나오든 막는다.
CI_FORBIDDEN_TEXT = ("OH_MY_HARNESS_PROBE", ".guardrail-nested")

# 실행 환경을 갈아끼우는 변수들. 이름 목록이라 닫히지 않는다 —
# docs/OPEN-FINDINGS.md §C-13 에 한계로 적어 두었다.
CI_FORBIDDEN_ENV = {"BASH_ENV", "PATH", "ENV", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES",
                    "PYTHONSTARTUP", "PYTHONPATH", "GITHUB_ENV", "GITHUB_PATH"}

CI_FORBIDDEN_MENTIONS = ("scripts/validate_repository.py",
                         "tests/guardrail/run_guardrail.py",
                         "scripts/harness_lint.py",
                         "scripts/preflight_runner.py",
                         "working-directory")


def _stage_declarations(errors: list[str] | None = None
                        ) -> tuple[list[tuple[str, ...]], list[str], int]:
    """(argv tails, callable names, total) declared in preflight_runner.py.

    This reader answers one question — *which gates are declared* — and nothing
    more. It used to also police how the declaration was written (argv must
    start with `PY`, no lambdas, no mutation afterwards). Those rules blocked
    ordinary refactoring and were bypassed anyway: `ALIAS = STAGES; ALIAS[:] =
    [(l, lambda: True) …]` satisfied every one of them while making all eight
    stages no-ops. Whether the declared gates actually run is a question about
    behaviour, and `_preflight_actually_enforces` answers it by running them.
    """
    return _stage_declarations_from(ROOT / "scripts" / "preflight_runner.py", errors)


def _stage_declarations_from(path: Path, errors: list[str] | None = None
                             ) -> tuple[list[tuple[str, ...]], list[str], int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assigns = [n for n in tree.body if isinstance(n, ast.Assign)
               and any(getattr(x, "id", None) == "STAGES" for x in n.targets)]
    if len(assigns) != 1 or not isinstance(assigns[0].value, ast.List):
        if errors is not None:
            errors.append("the stage file must assign STAGES exactly once, as a "
                          "list literal — anything else and this gate is reading a "
                          "program that is not the one that runs")
        return [], [], 0
    node = assigns[0].value

    argvs: list[tuple[str, ...]] = []
    callables: list[str] = []
    for elt in node.elts:
        if not isinstance(elt, ast.Tuple) or len(elt.elts) != 2 or \
                not isinstance(elt.elts[0], ast.Constant):
            if errors is not None:
                errors.append("every STAGES entry must be a (label, action) tuple with "
                              "a literal label")
            continue
        action = elt.elts[1]
        if isinstance(action, ast.List):
            # 인터프리터 뒤의 리터럴만 읽는다. 조립식 argv 는 여기서 «안 보이는» 것이지
            # 금지 대상이 아니다 — 그 단계가 실제로 도는지는 행동 관찰이 판정한다.
            rest = [a.value for a in action.elts[1:]
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            argvs.append(tuple(rest))
        elif isinstance(action, ast.Name):
            callables.append(action.id)
    return argvs, callables, len(node.elts)


# 프로브가 자식 실행에게 «너는 프로브 안이다» 를 알리는 방법. 파일이 아니라 환경변수다 —
# 파일이면 CI 가 앞 단계에서 `touch` 한 줄로 프로브를 통째로 끌 수 있었다(리뷰 13).
PROBE_ENV = "OH_MY_HARNESS_PROBE"

# 프로브가 심는 결함. 단계마다 하나씩 — 여덟 개 전부다.
#
# 리뷰 14가 세 개짜리 판을 뚫었다: 재지 않는 다섯 단계는 «실행 자체를 건너뛰어도»
# 통과했다(`if label == "repository gates": continue` 한 줄, 실측 rc=0). 재는 단계만
# 도는 러너와 전부 도는 러너를 구별하려면, 재는 범위가 곧 전부여야 한다.
#
# 그래서 기대값을 여기 적지 않고 러너의 STAGES 에서 «읽는다». 단계를 새로 더하고
# 여기 결함을 안 심으면 그 단계가 초록으로 돌아와 프로브가 실패한다 — 새 단계는
# 심을 결함과 함께 들어오라는 뜻이고, 그게 맞는 방향의 fail-closed 다.


def _stage_labels(path: Path) -> list[str]:
    """STAGES 의 라벨만 읽는다. 선언 파서와 같은 자리를 보되 반환을 안 바꾼다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(x, "id", None) == "STAGES" for x in node.targets):
            continue
        if not isinstance(node.value, ast.List):
            return []
        return [e.elts[0].value for e in node.value.elts
                if isinstance(e, ast.Tuple) and e.elts
                and isinstance(e.elts[0], ast.Constant)
                and isinstance(e.elts[0].value, str)]
    return []


def _replace_once(path: Path, anchor: str, replacement: str) -> str | None:
    """앵커가 없으면 «심었다» 고 말하지 않는다 — 빗나간 주입은 결과가 아니라 사고다."""
    text = path.read_text(encoding="utf-8")
    if anchor not in text:
        return f"{path.name} no longer contains the anchor {anchor.strip()[:60]!r}"
    path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
    return None


def _plant_probe_defects(copy: Path) -> str | None:
    """Plant one defect per stage, so every stage has to run to be seen failing."""
    edits = [
        # 1. guardrail self-test — 판정 함수가 «실패했다» 를 못 말하게 한다
        (copy / "tests/guardrail/run_guardrail.py",
         '    if result.returncode == 0:\n        return "did NOT fail"\n',
         '    return None\n    if result.returncode == 0:\n        return "did NOT fail"\n'),
        # 2. validator self-test — 자기시험이 부르는 운영 파서를 빈손으로 만든다
        (copy / "scripts/validate_repository.py",
         '    tree = ast.parse(path.read_text(encoding="utf-8"))\n',
         '    return [], [], 0\n    tree = ast.parse(path.read_text(encoding="utf-8"))\n'),
        # 4. guardrail suite — lint 규칙 하나를 무력화하면 그 규칙의 케이스가
        #    «did NOT fail» 로 돌아온다. (3·5~8 은 아래에서 따로 심는다)
        (copy / "scripts/harness_lint.py",
         '                out.append(Finding("agent-frontmatter", h.rel(p), f"frontmatter missing {field}:"))\n',
         '                pass\n'),
        # 6. nothing-to-lint returns 2, not 0
        (copy / "scripts/harness_lint.py",
         '        print(f"no harness found under {h.claude} — nothing to lint", file=sys.stderr)\n        return 2\n',
         '        print(f"no harness found under {h.claude} — nothing to lint", file=sys.stderr)\n        return 0\n'),
    ]
    for path, anchor, replacement in edits:
        why = _replace_once(path, anchor, replacement)
        if why:
            return why

    # 3. repository gates — 버전 정합성을 깬다(파싱은 그대로 되어야 하므로 값만 바꾼다)
    plugin = copy / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(plugin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"cannot rewrite plugin.json to break version consistency: {exc}"
    data["version"] = "0.0.0-probe"
    plugin.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    # 5. reference harness — 깨끗해야 할 픽스처에 이름이 겹치는 에이전트를 넣는다
    agents = sorted((copy / "tests/fixtures/clean-harness/.claude/agents").glob("*.md"))
    if not agents:
        return "the reference harness fixture has no agents to duplicate"
    first = agents[0].read_text(encoding="utf-8")
    (agents[0].parent / "probe-duplicate.md").write_text(first, encoding="utf-8")

    # 7. every JSON parses
    (copy / "docs" / "probe-invalid.json").write_text("{ not json", encoding="utf-8")
    # 8. no merge conflict markers
    (copy / "docs" / "probe-conflict.md").write_text(
        "<<<<<<< HEAD\na\n=======\nb\n>>>>>>> other\n", encoding="utf-8")
    return None


def _preflight_actually_enforces(errors: list[str]) -> None:
    """Run the entry point on a deliberately broken copy and read every stage.

    This replaces rules that pinned the *shape* of the runner's source. Shape
    pinning was wrong both ways at once — it accepted `if False: action()`
    (every marker present, nothing executed) and rejected ordinary refactoring.
    Source text is not behaviour.

    One planted defect is not enough either: a runner that skips every stage
    except the one being probed passed that version. Three were not enough
    either — review 14 skipped one of the five unmeasured stages and the run
    stayed green. So a defect goes into *every* stage and every stage must come
    back red. A stage that does not run cannot be seen failing.

    What this does not prove: the runner reports its own verdict, so a runner
    rewritten to print that summary without running anything passes. It is
    inside the trust boundary — see §D-7 in docs/OPEN-FINDINGS.md.
    """
    if os.environ.get(PROBE_ENV):
        return                        # already inside a probe; do not recurse
    expected = _stage_labels(ROOT / "scripts" / "preflight_runner.py")
    if not expected:
        errors.append("the runner declares no readable stage labels, so a probe would "
                      "have nothing to compare its result against")
        return
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "probe"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(
            ".git", "node_modules", "__pycache__", ".omc", ".omx"))
        # 사본에도 git 이 있어야 한다. 없으면 `dead-api` 가 「무엇이 우리 것인지 모른다」로
        # 정당하게 빨개지고, 심지도 않은 단계가 빨개져 패턴 판정이 무의미해진다.
        subprocess.run(["git", "init", "-q"], cwd=copy, capture_output=True, check=False)
        tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                                 capture_output=True, check=False).stdout
        subprocess.run(["git", "add", "--pathspec-from-file=-", "--pathspec-file-nul"],
                       cwd=copy, input=tracked, capture_output=True, check=False)
        why = _plant_probe_defects(copy)
        if why:
            errors.append(f"cannot probe whether preflight enforces: {why}, so this "
                          f"check would prove nothing")
            return
        try:
            res = subprocess.run(
                ["bash", "scripts/preflight.sh"], cwd=copy, capture_output=True,
                text=True, timeout=600,
                env=dict(os.environ, **{PROBE_ENV: "1"}))
        except subprocess.TimeoutExpired:
            errors.append("scripts/preflight.sh did not finish within 600s on a probe "
                          "copy — a gate that never returns blocks every push")
            return
    if res.returncode == 0:
        errors.append("scripts/preflight.sh reported success on a tree with a planted "
                      "defect in every stage — something between the stage list and "
                      "the process exit is not running them")
        return
    # 단계별 판정은 러너 자신의 요약에서 읽는다. 본문에서 "FAIL" 을 찾으면 단계마다
    # 실패를 다르게 표현한다는 사실에 걸린다("Invalid JSON:" 처럼).
    m = re.search(r"^preflight: FAILED[^(]*\((\d+)/(\d+) stages\)$", res.stdout, re.M)
    if not m:
        errors.append("scripts/preflight.sh did not report which stages failed — "
                      "without a per-stage verdict a red run is not evidence that any "
                      "particular stage ran")
        return
    failed = set(re.findall(r"^ *failed stage: (.+)$", res.stdout, re.M))
    ran = {part.partition("\n")[0].strip()
           for part in ("\n" + res.stdout).split("\n== ")[1:]}
    missing = sorted(set(expected) - ran)
    if missing:
        errors.append(f"these stages never ran on the probe copy: {missing} "
                      f"(stages seen: {sorted(ran)})")
        return
    if failed != set(expected):
        green = sorted(set(expected) - failed)
        extra = sorted(failed - set(expected))
        errors.append(
            f"the probe planted a defect in all {len(expected)} stages and preflight "
            f"reported {len(failed)} as failed. Sabotaged but green: {green} — a stage "
            f"that cannot be seen failing is a stage nothing proves is running. "
            f"Failed but not in the stage list: {extra}.")


def check_preflight_stages(errors: list[str]) -> None:
    """The entry point runs every gate this repository owns, and nothing hides it.

    The shell version declared its stages as `run "label" cmd` lines, and this
    gate tried to prove from that text that they really ran. Six bypasses got
    through in ten reviews, each a new blacklist entry, and `eval 'run() {…}'`
    showed the list would never end. So the stages moved into Python data and
    the shell shrank to two pinned lines.
    """
    before = len(errors)
    wrapper = ROOT / "scripts" / "preflight.sh"
    runner = ROOT / "scripts" / "preflight_runner.py"
    if not wrapper.is_file() or not runner.is_file():
        errors.append("scripts/preflight.sh and scripts/preflight_runner.py must both exist")
        return
    # `splitlines()` 를 쓰지 않는다: 파이썬은 U+0085·U+2028 도 줄 경계로 보는데
    # **bash 는 안 그런다**. 그 차이로 「주석 안에 든 exec」 가 두 줄로 보인다.
    # 그 입력을 «거부» 하지는 않는다 — 실제로 아무것도 안 돌기 때문에 아래의 행동
    # 프로브가 잡는다. 여기서는 세는 방식만 bash 에 맞춘다.
    #
    # 반대로 「주석 끝의 `\` 가 다음 줄을 먹는다」는 리뷰 지적은 **틀렸다**. 재현해
    # 보니 bash 는 주석 안의 백슬래시를 잇지 않고 다음 줄을 그대로 실행한다
    # (`# c \` + 개행 + `echo RAN` → RAN). 그 지적을 그대로 믿고 넣었던 결합 규칙을
    # 뺐다 — 없는 결함을 막던 규칙이었고, 그 케이스는 틀린 이유로 통과하고 있었다.
    raw = wrapper.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    # 셔뱅은 주석처럼 생겼지만 주석이 아니다 — 어떤 셸이 도는지 정하는 줄이다.
    effective = ([raw[0].rstrip()] if raw and raw[0].startswith("#!") else []) + [
        l.rstrip() for l in raw[1:] if l.strip() and not l.lstrip().startswith("#")]
    if effective != PREFLIGHT_WRAPPER_LINES:
        errors.append(f"scripts/preflight.sh is no longer the two-line wrapper. "
                      f"want {PREFLIGHT_WRAPPER_LINES}, got {effective}. Anything more "
                      f"is shell that can redefine, short-circuit or swallow a stage.")

    argvs, callables, total = _stage_declarations(errors)
    if not total:
        errors.append("scripts/preflight_runner.py declares no STAGES list")
        return
    for want in REQUIRED_STAGE_COMMANDS:
        if not any(tuple(a) == want for a in argvs):
            errors.append(f"preflight_runner.py has no stage running {' '.join(want)} — "
                          f"that gate exists and nothing calls it "
                          f"(stages declared: {argvs})")
    for name in REQUIRED_STAGE_CALLABLES:
        if name not in callables:
            errors.append(f"preflight_runner.py's STAGES no longer includes {name} — "
                          f"the function may still exist, but nothing runs it")

    # 프로브 신호를 저장소나 CI 에서 켜면 프로브가 통째로 꺼진다.
    if (ROOT / ".guardrail-nested").exists():
        errors.append(".guardrail-nested is a leftover from the old file-based probe "
                      "signal — delete it; the signal is now an environment variable "
                      "that a repository file cannot set")
    # 가드레일 스위트의 절이 다 불리는가. 호출 줄 하나를 지우면 그 절이 통째로 안 돈다.
    suite = (ROOT / "tests" / "guardrail" / "run_guardrail.py").read_text(encoding="utf-8")
    called = set(re.findall(r"^\s*(\w+)\(failures, args\.verbose\)", suite, re.M))
    for section in REQUIRED_GUARDRAIL_SECTIONS:
        if section not in called:
            errors.append(f"tests/guardrail/run_guardrail.py never calls {section}() — "
                          f"that whole section of the suite is silently skipped")
    # 호출돼도 «잴 것이 없으면» 같은 결과다. 목록이 비면 그 절은 조용히 no-op 이다.
    m2 = re.search(r"^PREFLIGHT_ENFORCEMENT\s*=\s*\[(.*?)^\]", suite, re.M | re.S)
    if not m2:
        errors.append("tests/guardrail/run_guardrail.py no longer declares "
                      "PREFLIGHT_ENFORCEMENT")
    elif len(re.findall(r'^\s{4}\("', m2.group(1), re.M)) < 2:
        errors.append("PREFLIGHT_ENFORCEMENT has fewer than 2 entries — the section "
                      "still runs and proves nothing")

    # 마지막으로, 그리고 정적 검사가 아무 말도 안 했을 때만: 진입점을 «돌려서» 본다.
    # 이미 지적이 있으면 게이트는 어차피 빨갛고, 프로브는 시간만 쓴다.
    if len(errors) == before:
        _preflight_actually_enforces(errors)


def check_ci_runs_preflight(errors: list[str]) -> None:
    """CI runs the entry point, and something actually starts CI.

    v2.7.0 shipped with a failing guardrail because the push command ran one
    gate out of three. preflight.sh exists to stop that, but only while the
    thing that blocks a merge calls it — and only while something starts it.

    Four earlier versions tried to answer this by reading the file as text.
    All four were wrong, each in a new way: a header comment counted as a
    step; an action's `with: run:` counted as a step; a `>` fold turned the
    command into a shell comment; a fake `- name:` inside a job's `name: |2`
    block put the required lines at what *looked* like step position while the
    real steps ran `echo`. Text position is not YAML structure.

    So parse it. With the document in hand the questions are direct — which job
    runs these commands, is that job conditional, do its triggers actually fire
    — and unrelated jobs get to use `if:` and `shell:` freely, which the text
    version had to forbid outright.
    """
    wf = ROOT / ".github" / "workflows" / "validation.yml"
    if not wf.is_file():
        errors.append(".github/workflows/validation.yml is missing")
        return
    try:
        import yaml
    except ImportError:
        errors.append("PyYAML is not available, so this gate cannot read "
                      "validation.yml. It fails closed on purpose: an unverified "
                      "workflow is not a verified one")
        return
    try:
        doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        errors.append(f"validation.yml is not valid YAML: {exc}")
        return
    if not isinstance(doc, dict):
        errors.append("validation.yml does not parse to a mapping")
        return

    # PyYAML reads a bare `on:` key as the boolean True (YAML 1.1).
    triggers = doc.get("on", doc.get(True))
    _check_ci_triggers(triggers, errors)

    raw = wf.read_text(encoding="utf-8")
    for name in CI_FORBIDDEN_TEXT:
        if name in raw:
            errors.append(f"validation.yml mentions {name} — that switches off the check "
                          f"that preflight actually enforces its gates, and CI must not "
                          f"be where it gets set")

    jobs = doc.get("jobs") or {}
    gate_jobs = []
    for name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        runs = [str(s.get("run", "")).strip()
                for s in (job.get("steps") or []) if isinstance(s, dict)]
        if all(want in runs for want in CI_REQUIRED_STEP_RUNS):
            gate_jobs.append((name, job, runs))
    if not gate_jobs:
        errors.append(
            f"no job in validation.yml runs both {CI_REQUIRED_STEP_RUNS!r} as its own "
            f"`run:` steps — CI must run the entry point verbatim, and the integrity "
            f"check that does not trust its exit code")
        return

    for name, job, runs in gate_jobs:
        order = [runs.index(w) for w in CI_REQUIRED_STEP_RUNS]
        if order != sorted(order):
            errors.append(f"job {name!r} runs preflight before the integrity check — "
                          f"that step exists to distrust preflight's exit code")
        if "if" in job:
            errors.append(f"job {name!r} is conditional (`if: {job['if']}`) — the gate "
                          f"can then be skipped with every required line in place")
        if job.get("continue-on-error"):
            errors.append(f"job {name!r} sets continue-on-error — a red gate would not "
                          f"block anything")
        # `defaults:` 자체는 죄가 없다 — 위험한 것은 셸 교체 하나다
        # (`shell: true {0}` 이면 모든 `run:` 이 아무것도 안 하고 성공한다).
        # working-directory 가 엉뚱하면 명령을 못 찾아 «빨개지므로» fail-closed 다.
        for scope, block in (("workflow", doc.get("defaults")),
                             (f"job {name!r}", job.get("defaults"))):
            if isinstance(block, dict) and "shell" in (block.get("run") or {}):
                errors.append(f"a `defaults.run.shell` applies to {scope} — a custom "
                              f"shell turns every `run:` into a no-op that succeeds")
        if "needs" in job:
            errors.append(f"job {name!r} declares `needs:` — GitHub skips a job whose "
                          f"prerequisite was skipped, so a conditional upstream job "
                          f"switches this gate off with every required line in place")
        if "container" in job or "services" in job:
            errors.append(f"job {name!r} runs in a container it defines here — the "
                          f"`python3` and `bash` the gate calls would come from that "
                          f"image, and this file cannot say what is in it")
        # 실행 «환경» 을 바꾸면 명령을 안 바꾸고도 명령의 뜻을 바꿀 수 있다.
        # `BASH_ENV` 를 가리키는 파일에서 `exit 0` 하면 두 canonical 스텝이 시작되기
        # 전에 성공 종료된다(리뷰 14 실측). PATH 는 python3·bash 를 바꿔치기한다.
        env_scopes = [("workflow", doc.get("env")), (f"job {name!r}", job.get("env"))]
        for step in job.get("steps") or []:
            if isinstance(step, dict) and str(step.get("run", "")).strip() \
                    in CI_REQUIRED_STEP_RUNS:
                env_scopes.append((f"the gate step in job {name!r}", step.get("env")))
        for scope, env in env_scopes:
            if not isinstance(env, dict):
                continue
            hostile = sorted(k for k in env if k.upper() in CI_FORBIDDEN_ENV)
            if hostile:
                errors.append(f"{scope} sets {hostile} — that reprograms the shell the "
                              f"gate runs in without touching a single `run:` line")
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            run = str(step.get("run", "")).strip()
            if run in CI_REQUIRED_STEP_RUNS:
                if "if" in step or step.get("continue-on-error"):
                    errors.append(f"the gate step in job {name!r} is conditional or "
                                  f"ignores failure")
                # `shell: bash` 는 ubuntu 러너의 기본값을 명시한 것뿐이다. 막을 이유가
                # 없고, 막았더니 정상 기여자가 걸렸다(리뷰 14).
                if step.get("shell", "bash") != "bash":
                    errors.append(f"the gate step in job {name!r} sets "
                                  f"`shell: {step['shell']}` — `shell: true {{0}}` "
                                  f"succeeds without running anything")
                continue
            for forbidden in CI_FORBIDDEN_MENTIONS:
                if forbidden in run:
                    errors.append(f"job {name!r} runs {forbidden} outside the two "
                                  f"canonical steps — re-listing the gates here is how "
                                  f"this file and preflight drift apart")


def _check_ci_triggers(triggers: object, errors: list[str]) -> None:
    """Something has to start the workflow, on the branch that matters.

    Leaving only `workflow_dispatch`, or filtering `branches` down to one that
    never exists, or `paths-ignore: ["**"]` — each leaves every required line
    exactly where it was and no run ever happens.
    """
    if isinstance(triggers, str):
        triggers = {triggers: None}
    elif isinstance(triggers, list):
        triggers = {k: None for k in triggers}
    if not isinstance(triggers, dict):
        errors.append("validation.yml has no readable `on:` triggers")
        return
    for event in ("pull_request", "push"):
        if event not in triggers:
            errors.append(f"validation.yml does not trigger on {event} — the gate exists "
                          f"and nothing starts it")
            continue
        cfg = triggers[event] or {}
        if not isinstance(cfg, dict):
            continue
        for key in ("paths", "paths-ignore"):
            if key in cfg:
                errors.append(f"validation.yml filters {event} by {key} — the gate must "
                              f"run for every change, not only for some paths")
        if event == "pull_request":
            # `types:` 를 주면 그 활동에서만 돈다. `[closed]` 만 남기면 PR 을 갱신해도
            # 아무 일이 없다 — 필수 줄은 전부 제자리인 채로(리뷰 14 실측).
            types = cfg.get("types")
            if types is not None:
                missing = [a for a in ("opened", "synchronize", "reopened")
                           if a not in (types or [])]
                if missing:
                    errors.append(f"validation.yml limits pull_request to {types} — "
                                  f"{missing} would not start the gate, so a PR can be "
                                  f"opened or updated without it ever running")
        if event == "push" and "tags" in cfg and "branches" not in cfg:
            errors.append("validation.yml triggers push on tags only — pushing a branch "
                          "never starts the gate")
        branches = cfg.get("branches")
        negated = [b for b in (branches or []) if isinstance(b, str) and b.startswith("!")]
        if negated:
            errors.append(f"validation.yml excludes {negated} from {event} — a pattern "
                          f"list can name the protected branch and then take it back")
        if branches is not None and not any(
                b in ("main", "**", "*") for b in (branches or [])):
            errors.append(f"validation.yml restricts {event} to {branches} — the gate "
                          f"never runs on the branch it is meant to protect")
        if "branches-ignore" in cfg:
            errors.append(f"validation.yml uses branches-ignore for {event} — that can "
                          f"exclude the branch this gate protects")


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
# (워크플로우 조각, 실행 단계로 읽혀야 하는 명령들) — `run:` 본문을 뽑아내는 파서가
# 이 판정의 전부다. 주석·블록 스칼라를 잘못 읽으면 「CI 가 게이트를 부른다」가 거짓이 된다.
# (러너 소스 조각, 읽혀야 하는 argv 꼬리들, 콜러블 이름들)
# `STAGES` 를 구문 트리로 읽는 것이 「게이트가 실제로 불린다」의 근거 전부다.
STAGES_SELF_TEST = [
    ('STAGES = [\n    ("a", [PY, "x.py"]),\n]\n', [("x.py",)], []),
    ('STAGES = [\n    ("a", [PY, "x.py", "--flag"]),\n    ("b", fn),\n]\n',
     [("x.py", "--flag")], ["fn"]),
    # 목록이 비면 «단계가 없다» 이지 «다 있다» 가 아니다
    ("STAGES = [\n]\n", [], []),
    # 다른 이름의 목록은 STAGES 가 아니다
    ('OTHER = [\n    ("a", [PY, "x.py"]),\n]\n', [], []),
]


def self_test() -> int:
    """Test this file's own reading of the runner's stage declarations.

    Everything the preflight gate claims rests on this: if `STAGES` is misread,
    "that gate exists and nothing calls it" is decided on nothing. The previous
    judge here parsed shell and then YAML, and was wrong in both — six bypasses
    and three false readings. Data is easier to be right about, but only if the
    reading is pinned.
    """
    fail = 0

    def read(src: str):
        """운영 파서를 그대로 부른다. 자기시험이 «사본» 을 시험하면 시험한 적이 없다."""
        # 고정 경로를 쓰면 같은 이름의 사용자 파일을 지운다(리뷰 14 실측). 임시
        # 디렉터리면 병렬 실행끼리도 안 부딪힌다.
        with tempfile.TemporaryDirectory() as box:
            tmp = Path(box) / "runner.py"
            tmp.write_text(src, encoding="utf-8")
            argvs, calls, _ = _stage_declarations_from(tmp)
        return argvs, calls

    for src, want_argv, want_calls in STAGES_SELF_TEST:
        got = read(src)
        if got == (want_argv, want_calls):
            print(f"  ok  STAGES of {src.splitlines()[0]!r} -> {got}")
        else:
            print(f"FAIL {src!r}\n     got {got}, want {(want_argv, want_calls)}",
                  file=sys.stderr)
            fail = 1

    # 실제 러너도 같은 방식으로 읽혀야 한다 — 합성 입력만 맞고 진짜가 틀리면 소용없다
    argvs, calls, total = _stage_declarations()
    if total >= len(REQUIRED_STAGE_COMMANDS) + len(REQUIRED_STAGE_CALLABLES):
        print(f"  ok  the real runner declares {total} stages "
              f"({len(argvs)} commands, {len(calls)} callables)")
    else:
        print(f"FAIL the real runner declares only {total} stages", file=sys.stderr)
        fail = 1
    if len(CI_REQUIRED_STEP_RUNS) == 2 and len(REQUIRED_STAGE_COMMANDS) >= 4:
        print(f"  ok  contracts declare {len(REQUIRED_STAGE_COMMANDS)} runner commands "
              f"and {len(CI_REQUIRED_STEP_RUNS)} CI steps")
    else:
        print("FAIL the required-command contracts were emptied", file=sys.stderr)
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
