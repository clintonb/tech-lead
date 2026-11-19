#!/usr/bin/env bash
# Usage: lead.sh <project> [--bypass] [claude args...]   (state lives in ~/.claude/leads/<project>/)
# Starts a fresh Claude session as the tech lead. Inside a session, `/tech-lead:lead <project>` does the same.
# Bypass permissions mode stays reachable with shift+tab. --bypass starts in it.
# Deny rules and hooks still apply in bypass, and pr-workers inherit the mode.
set -euo pipefail
PROJECT="${1:?usage: lead.sh <project> [--bypass] [claude args...]}"; shift
args=()
for a in "$@"; do
  if [[ "$a" == --bypass ]]; then args+=(--permission-mode bypassPermissions); else args+=("$a"); fi
done
mkdir -p "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/leads/$PROJECT"
LEAD_PROJECT="$PROJECT" exec claude --agent tech-lead:tech-lead --allow-dangerously-skip-permissions ${args[@]+"${args[@]}"}
