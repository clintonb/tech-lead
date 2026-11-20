#!/usr/bin/env bash
# Usage: lead.sh <project> [--ask] [claude args...]   (state lives in ~/.claude/leads/<project>/)
# Starts a fresh Claude session as the tech lead. Inside a session, `/tech-lead:lead <project>` does the same.
# Starts in bypass permissions mode. --ask (or an explicit --permission-mode) starts with prompts instead.
# Deny rules and hooks still apply in bypass, and pr-workers inherit the mode.
set -euo pipefail
PROJECT="${1:?usage: lead.sh <project> [--ask] [claude args...]}"; shift
mode=(--permission-mode bypassPermissions)
args=()
for a in "$@"; do
  case "$a" in
    --ask) mode=() ;;
    --bypass) ;;
    --permission-mode|--permission-mode=*) mode=(); args+=("$a") ;;
    *) args+=("$a") ;;
  esac
done
mkdir -p "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/leads/$PROJECT"
LEAD_PROJECT="$PROJECT" exec claude --agent tech-lead:tech-lead --allow-dangerously-skip-permissions ${mode[@]+"${mode[@]}"} ${args[@]+"${args[@]}"}
