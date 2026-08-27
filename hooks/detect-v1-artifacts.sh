#!/usr/bin/env bash
# New in oh-my-harness. Not derived from upstream.
#
# Warn once, at session start, when this project's harness still instructs an
# API Claude Code removed in 2.1.178. Markdown does not error on a missing
# tool — the model improvises — so without this the breakage is silent.
#
# Silent and near-free when there is nothing to say: it does not look at all
# unless .claude/agents exists.
set -u
d="${CLAUDE_PROJECT_DIR:-$PWD}/.claude"
[ -d "$d/agents" ] || exit 0

# Match the token, then drop lines that are describing the removal rather than
# instructing it. Filtering per LINE matters: `grep -vl` would drop a file for
# having any unrelated non-matching line, which is not the same question.
hits=$(grep -rnE 'TeamCreate|TeamDelete|CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS' \
         "$d/agents" "$d/skills" 2>/dev/null \
       | grep -viE '제거|삭제|없다|없습니다|존재하지 않|잔재|금지|removed|no longer|does not exist|deprecated|legacy|gone|dropped' \
       | cut -d: -f1 | sort -u | head -5)
[ -n "$hits" ] || exit 0

echo "oh-my-harness: this project's harness instructs APIs removed in Claude Code 2.1.178:"
printf '  %s\n' $hits
echo "  Run /oh-my-harness:harness-audit for the migration path."
