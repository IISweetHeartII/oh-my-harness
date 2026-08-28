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
# preflight 가 «정확히» 실행해야 하는 명령. 위치 파싱 대신 글자 대조다 —
# 우리가 쓴 파일이고, 형태가 바뀌면 여기도 같이 바꾸는 것이 맞다.
REQUIRED_PREFLIGHT_COMMANDS = [
    "python3 tests/guardrail/run_guardrail.py --self-test",
    "python3 scripts/validate_repository.py --self-test",
    "python3 scripts/validate_repository.py",
    "python3 tests/guardrail/run_guardrail.py",
    "python3 scripts/harness_lint.py tests/fixtures/clean-harness",
]

# CI 가 «정확히» 실행해야 하는 단계, 순서대로. 무결성 확인이 먼저다.
CI_REQUIRED_STEPS = [
    "python3 scripts/validate_repository.py --only preflight-stages",
    "bash scripts/preflight.sh",
]

# CI 의 실행 단계에 이 이름들이 위 두 줄 «말고» 나오면 게이트 목록이 갈라지는 중이다.
CI_FORBIDDEN_MENTIONS = ("scripts/validate_repository.py",
                         "tests/guardrail/run_guardrail.py",
                         "scripts/harness_lint.py")

# preflight 의 «실행기» 는 글자 그대로 이 모양이어야 한다.
#
# 왜 (2026-08-28 실측): 호출 줄도 STAGES_EXPECTED 도 그대로 둔 채 run() 만
# 「--self-test 이면 그냥 return 0」 으로 고쳤더니, 그 단계가 한 번도 안 돌았는데
# preflight-stages 도 preflight 도 초록이었다. 게이트가 «호출 줄» 을 보고 있었지
# «실행» 을 보고 있지 않았다. 스크립트는 자기 자신에 대한 편집을 막을 수 없으니
# 판정은 바깥 파일이 한다.
# 가드레일 스위트가 «반드시 부르는» 절. 한 줄을 지우면 그 절 전체가 조용히 사라진다 —
# 스위트 안에서는 아무도 모르고, 요약 문장만 짧아진다. 그래서 밖에서 센다.
REQUIRED_GUARDRAIL_SECTIONS = ("guardrail_harness_lint", "guardrail_valid_variants",
                               "guardrail_preflight_enforces",
                               "guardrail_allowlist_suggestion")

# 가드레일이 preflight 를 재귀 없이 돌리기 위한 표시. 사본 안에만 만드는 «파일» 이다 —
# 환경변수로 두었더니 워크플로우 밖에서 켜는 길이 여럿이었다(composite action 이
# `$GITHUB_ENV` 에 쓰기 · self-hosted runner 환경 · preflight 안에서 export).
# 파일은 저장소 안에 있어야 효력이 있고, 있으면 이 게이트가 본다.
GUARDRAIL_NEST_MARKER = ".guardrail-nested"

# preflight.sh 가 정의해도 되는 함수. 그 밖의 정의는 전부 거부한다.
PREFLIGHT_ALLOWED_FUNCTIONS = {"run", "stage"}

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
    canonical = [_canonical(c) for c in commands]
    for want in REQUIRED_PREFLIGHT_COMMANDS:
        if want not in canonical:
            errors.append(f"scripts/preflight.sh has no stage running exactly "
                          f"`{want}` — that gate exists and nothing calls it. "
                          f"(stages found: {'; '.join(canonical) or 'none'})")
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
    #
    # 이 고정은 «본 적 있는» 변조만 막는다. 정적 고정만 두었더니 한 자리에서 셋이
    # 더 뚫렸다 — 중복 정의 · 실행자 셰도잉 · exit 0. 진짜 판정은 가드레일이
    # preflight 를 «실제로 돌려서» 한다. 여기 넷은 그 위의 얇은 그물이다.
    # 줄 연결(`\` + 개행)은 bash 가 파싱 «전에» 지운다. 정의를 세기 «전에» 우리도
    # 지운다 — 안 그러면 `r\<개행>un() { … }` 가 두 번째 정의인데 한 줄로 안 보인다.
    joined = text.replace("\\\n", "")
    for name, want in PREFLIGHT_RUNNER_BODIES.items():
        # `name()` 과 `function name` 둘 다 정의다. 앞의 것만 세면 `function run { … }`
        # 로 no-op 을 덮어쓸 수 있다.
        defs = [l.strip() for l in joined.splitlines()
                if re.match(rf"(function\s+{re.escape(name)}\b|{re.escape(name)}\s*\(\))", l.strip())]
        if not defs:
            errors.append(f"scripts/preflight.sh no longer defines {name}()")
        elif len(defs) > 1:
            # 나중 정의가 앞 정의를 덮는다. 정경 정의를 그대로 두고 아래에 하나 더
            # 놓으면 「첫 줄만 보는」 고정은 그대로 통과했다(실측).
            errors.append(f"scripts/preflight.sh defines {name}() {len(defs)} times — "
                          f"the last definition wins and the canonical one is decoration")
        elif defs[0] != want:
            errors.append(
                f"scripts/preflight.sh's {name}() is not the canonical runner — "
                f"a stage can be counted without being executed. "
                f"want: {want}  ||  got: {defs[0]}")
    # 이 스크립트가 정의해도 되는 함수는 둘뿐이다. 실행자 이름(`python3`·`bash`…)을
    # 함수로 가리면 그 이름을 쓰는 단계가 조용히 no-op 이 되고, 이름을 열거해 막으려
    # 하면 bash 의 정의 문법을 전부 알아야 한다. 허용 목록이 훨씬 짧다.
    #
    for m in re.finditer(
            r"^[ \t]*(?:function[ \t]+([A-Za-z_][A-Za-z0-9_.-]*)"
            r"|([A-Za-z_][A-Za-z0-9_.-]*)[ \t]*\([ \t]*\))",
            joined, re.M):
        name = m.group(1) or m.group(2)
        if name not in PREFLIGHT_ALLOWED_FUNCTIONS:
            errors.append(f"scripts/preflight.sh defines a shell function named "
                          f"{name} — only {sorted(PREFLIGHT_ALLOWED_FUNCTIONS)} may be "
                          f"defined here. A function named after an interpreter turns "
                          f"every stage that uses it into a silent no-op.")
    # 재귀 표시가 «추적되면» 모든 체크아웃에서 강제 확인이 건너뛰어진다.
    #
    # 「존재하면」이 아니라 「추적되면」인 이유: 중첩 실행되는 사본에는 이 파일이
    # 정당하게 있고(그게 재귀를 끊는 장치다), 거기서 이 게이트가 울면 강제 확인이
    # «엉뚱한 단계» 에서 빨개져 증거가 못 된다. 추적되지 않은 로컬 파일은 그 사람의
    # 작업 사본에만 영향을 주고 CI 의 신선 체크아웃에는 없다 — 다른 로컬 수정과 같다.
    if subprocess.run(["git", "ls-files", "--error-unmatch", GUARDRAIL_NEST_MARKER],
                      cwd=ROOT, capture_output=True).returncode == 0:
        errors.append(f"{GUARDRAIL_NEST_MARKER} is tracked by git — that file tells the "
                      f"guardrail it is already inside a preflight run, so the check "
                      f"that preflight enforces its gates would skip in every "
                      f"checkout. It belongs only inside a temporary copy.")
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
    # 종료 코드. `exit 0` 이면 모든 게이트가 빨개져도 이 스크립트는 성공을 보고한다.
    # 스크립트는 자기 종료코드를 검사할 수 없으므로, 이 줄을 «밖에서» 확인하는
    # 무결성 스텝(CI·pre-push 훅 첫 줄)이 짝을 이룬다.
    effective = [l.rstrip() for l in text.splitlines()
                 if l.strip() and not l.lstrip().startswith("#")]
    if not effective or not re.fullmatch(r'exit "?\$fail"?', effective[-1].strip()):
        errors.append("scripts/preflight.sh's last effective line is "
                      f"{(effective[-1].strip() if effective else '(nothing)')!r}, "
                      "not `exit $fail` — a stage can fail while the script reports "
                      "success. Checking that the line merely exists let an `exit 0` "
                      "sit above the stages with the real line still below it.")
    stray = [l for l in effective if re.fullmatch(r"exit\s+\d+", l.strip())]
    # 같은 결과를 내는 다른 두 길(리뷰 9): 마지막에 `fail=0` 을 한 번 더 놓기,
    # `trap ... EXIT` 로 종료를 가로채기. 둘 다 «단계는 다 돌았는데 결과만 거짓» 이다.
    resets = [l for l in effective if re.fullmatch(r"fail=0", l.strip())]
    if len(resets) != 1 or effective.index(resets[0]) > effective.index(
            next((l for l in effective if l.lstrip().startswith("run ")), effective[-1])):
        errors.append(f"scripts/preflight.sh sets `fail=0` {len(resets)} time(s) and not "
                      f"only before the stages — a second reset erases every failure "
                      f"while every stage still runs")
    if any(l.lstrip().startswith("trap ") for l in effective):
        errors.append("scripts/preflight.sh installs a `trap` — an EXIT trap can "
                      "replace the script's result after every stage has run")
    if stray:
        errors.append("scripts/preflight.sh contains a literal `exit <n>` — "
                      "the script must end on `exit $fail` and nowhere else decide "
                      "its own result")


# 임의의 셸을 파싱해 「이게 실행되는가」를 맞히려던 시도는 여덟 차례 리뷰 중 네 번
# 뚫렸다 — `bash -n`, `command -v`, 죽은 분기, `if false`, 히어독, 안 불리는 함수,
# `bash -c ':' x.sh`, `-O extglob`… 셸 문법은 유한하지 않고, 우리는 셸을 구현하는 게
# 아니다. **그래서 계약을 좁혔다**: 이 저장소가 스스로 부르는 명령은 우리가 쓴 것이고,
# 정확히 이 글자여야 한다. 파싱이 아니라 대조다.
def _canonical(command: str) -> str:
    """Whitespace-normalised command text, comments stripped."""
    return " ".join(_strip_shell_comments(command).split())


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
    """CI must run the same script a human runs — and exactly it.

    v2.7.0 shipped with a failing guardrail because the push command ran one
    gate out of three. preflight.sh exists to stop that, but only while the
    thing that actually blocks a merge calls it.

    Earlier versions tried to decide "does this shell snippet execute the
    script" by parsing. Four separate reviews broke that parser — `bash -n`,
    `command -v`, `false && …`, `if false; then … fi`, a heredoc, an uncalled
    function, `bash -c ':' x.sh`, `-O extglob`. Shell grammar is not a finite
    list and we are not writing a shell. So the contract is narrower and the
    check is a comparison, not a parse: CI runs these exact commands. Anything
    else — a wrapper, a Makefile target, `|| true` — is refused loudly, which
    is the safe direction for a gate.
    """
    wf = ROOT / ".github" / "workflows" / "validation.yml"
    if not wf.is_file():
        errors.append(".github/workflows/validation.yml is missing")
        return
    text = wf.read_text(encoding="utf-8")
    steps = [_canonical(c) for c in _workflow_run_commands(text)]
    steps = [s for s in steps if s]
    if not steps:
        errors.append("validation.yml has no run: step that executes anything")
        return

    for want in CI_REQUIRED_STEPS:
        if want not in steps:
            errors.append(
                f"no run: step in validation.yml is exactly `{want}`. CI must run "
                f"the entry point verbatim — a wrapper or a swallowed exit code "
                f"turns the green tick into 'the gates CI knows about'. "
                f"(steps found: {'; '.join(steps)})")
    # 무결성 확인이 preflight «앞» 이어야 한다. 뒤에 있어도 잡히긴 하지만,
    # 문서가 「앞」이라고 말하고 있으므로 둘을 갈라 두지 않는다.
    if all(w in steps for w in CI_REQUIRED_STEPS) and \
            steps.index(CI_REQUIRED_STEPS[0]) > steps.index(CI_REQUIRED_STEPS[1]):
        errors.append("validation.yml runs preflight before the integrity check — "
                      "the point of that step is to distrust preflight's exit code, "
                      "so it goes first, as the docs say")
    for step in steps:
        if step in CI_REQUIRED_STEPS:
            continue
        for name in CI_FORBIDDEN_MENTIONS:
            if name in step:
                errors.append(f"a run: step mentions {name} outside the two canonical "
                              f"commands (`{step}`) — re-listing the gates here is how "
                              f"this file and preflight.sh drift apart")


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
WORKFLOW_SELF_TEST = [
    ("      - run: bash scripts/preflight.sh\n", ["bash scripts/preflight.sh"]),
    ("      - name: x\n        run: bash scripts/preflight.sh\n",
     ["bash scripts/preflight.sh"]),
    # 블록 스칼라 — 여러 줄이 한 단계다
    ("      - run: |\n          set -e\n          bash scripts/preflight.sh\n",
     ["set -e bash scripts/preflight.sh"]),
    # 셸 주석만 있는 단계는 «아무것도 실행하지 않는다»
    ("      - run: |\n          # bash scripts/preflight.sh\n", [""]),
    # 헤더 주석은 단계가 아니다
    ("# bash scripts/preflight.sh\njobs:\n  a:\n    steps:\n"
     "      - run: echo hi\n", ["echo hi"]),
]


def self_test() -> int:
    """Test this file's own parsing, on the shapes that fooled it before.

    `_workflow_run_commands` is what "CI runs the gate" now rests on. Reading
    the workflow as one string counted the header comment; reading a `run:`
    step as one line missed block scalars; not stripping shell comments let a
    commented-out call satisfy the gate. All three shipped.
    """
    fail = 0
    for source, want in WORKFLOW_SELF_TEST:
        got = [_canonical(c) for c in _workflow_run_commands(source)]
        if got == want:
            print(f"  ok  run: steps of {source.splitlines()[0].strip()!r} -> {got}")
        else:
            print(f"FAIL {source!r}\n     got {got}, want {want}", file=sys.stderr)
            fail = 1
    # 계약 자체도 시험한다 — 목록이 비면 위 게이트들이 아무것도 요구하지 않는다
    if len(REQUIRED_PREFLIGHT_COMMANDS) < 4 or len(CI_REQUIRED_STEPS) != 2:
        print("FAIL the required-command contracts were emptied", file=sys.stderr)
        fail = 1
    else:
        print(f"  ok  contracts declare {len(REQUIRED_PREFLIGHT_COMMANDS)} preflight "
              f"commands and {len(CI_REQUIRED_STEPS)} CI steps")
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
