#!/usr/bin/env bash
# Prints the default branch of the repo at <path>.
# Usage: default-branch.sh [repo-path]
set -euo pipefail
cd "${1:-.}"
if b=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null); then echo "${b#origin/}"; exit 0; fi
if b=$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name 2>/dev/null) && [[ -n "$b" ]]; then
  git remote set-head origin "$b" >/dev/null 2>&1 || true
  echo "$b"; exit 0
fi
echo master
