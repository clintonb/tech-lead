#!/usr/bin/env bash
# Usage: lead-mode.sh <project> | off   Switches the calling Claude session into (or out of) tech-lead mode.
set -euo pipefail
SID="${CLAUDE_CODE_SESSION_ID:?run this from inside a Claude Code session}"
LEADS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/leads"; DIR="$LEADS/.sessions"; mkdir -p "$DIR"
if [[ "${1:-}" == off ]]; then rm -f "$DIR/$SID"; echo "Session $SID is no longer a tech lead."; exit 0; fi
PROJECT="${1:-$(basename "$PWD")}"
mkdir -p "$LEADS/$PROJECT"
printf '%s\n' "$PROJECT" > "$DIR/$SID"
echo "Session $SID is now the tech lead for $PROJECT. Lead dir: $LEADS/$PROJECT"
