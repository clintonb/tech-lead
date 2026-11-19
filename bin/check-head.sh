#!/usr/bin/env bash
# Runs the repo's static checks on HEAD and records a pass, which push-check-gate.py requires before any git push.
# Usage: check-head.sh [repo-path]
set -euo pipefail
cd "${1:-.}"
SHA=$(git rev-parse HEAD)
MARKS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/tech-lead/state/checks"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || { echo "check-head: commit or drop tracked changes first; the checks must see exactly what gets pushed" >&2; exit 1; }
git fetch --quiet origin "$("$(dirname "$(realpath "$0")")/default-branch.sh" .)"
# The repo declares its own static checks: a lint:strict:changed script set, a package.json `check` script, or an
# executable scripts/check or scripts/lint (the scripts-to-rule-them-all layout).
has_script() { [[ -f package.json ]] && node -e 'process.exit(require("./package.json").scripts?.[process.argv[1]] ? 0 : 1)' "$1"; }
if [[ -f .nvmrc ]]; then set +u; . ~/.nvm/nvm.sh >/dev/null && nvm use >/dev/null; set -u; fi
# go.mod pins the Go version the way .nvmrc pins Node. A newer local Go breaks linters built for the pinned one.
if [[ -f go.mod ]]; then
  GOVER=$(awk '$1=="toolchain"{print $2; exit}' go.mod); [[ -n "$GOVER" ]] || GOVER=go$(awk '$1=="go"{print $2; exit}' go.mod)
  export GOTOOLCHAIN="$GOVER"
fi
if has_script lint:strict:changed; then
  pnpm typecheck
  pnpm lint
  pnpm lint:strict:changed
  pnpm check-format
elif has_script check; then
  pnpm check
elif [[ -x scripts/check || -x scripts/lint ]]; then
  # CI in this layout runs scripts/bootstrap first, which installs what the checks need.
  [[ ! -x scripts/bootstrap ]] || scripts/bootstrap
  if [[ -x scripts/check ]]; then scripts/check; else scripts/lint; fi
else
  echo "check-head: this repo declares no static checks. Add a package.json \"check\" script or an executable scripts/check to the repo in its own PR." >&2
  exit 1
fi
mkdir -p "$MARKS" && date -u +%FT%TZ > "$MARKS/$SHA"
echo "check-head: $SHA passed the static checks" >&2
