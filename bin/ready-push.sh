#!/usr/bin/env bash
# The only push path for pr-worker agents: static checks, base gate, then git push.
# Usage: ready-push.sh [--dry-run] <repo-path> <lead-dir> [extra git push args, e.g. --force-with-lease]
# A base other than the repo's default branch needs the unit's stackOn and stackReason in <lead-dir>/state.json, or the owner's `allow-stack <branch>`.
set -euo pipefail

DRY=""
if [[ "${1:-}" == "--dry-run" ]]; then DRY=1; shift; fi
REPO="${1:?repo path}"; LEAD_DIR="${2:?lead dir}"; shift 2

run() {
  bash -lc "cd $(printf %q "$REPO") && $1"
}
fail() { echo "ready-push: $*" >&2; exit 1; }
HERE=$(dirname "$(realpath "$0")")

DEFAULT=$("$HERE/default-branch.sh" "$REPO")
GH_REPO="${READY_PUSH_GH_REPO:-$(run "git remote get-url origin" | sed -E 's#^(https://github.com/|git@github.com:)##; s#\.git$##')}"
BRANCH=$(run "git rev-parse --abbrev-ref HEAD")
[[ "$BRANCH" != "$DEFAULT" && "$BRANCH" != "HEAD" ]] || fail "refusing to push from $BRANCH"
run "git fetch --quiet origin $DEFAULT"

PR_INFO=$(gh pr view "$BRANCH" --repo "$GH_REPO" --json baseRefName,state --jq '"\(.baseRefName) \(.state)"' 2>/dev/null || echo "$DEFAULT NONE")
BASE=${PR_INFO% *}
if [[ "$BASE" != "$DEFAULT" ]] && ! python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import lead_lib; sys.exit(0 if lead_lib.stack_allowed(sys.argv[2], sys.argv[3], sys.argv[4]) else 1)' "$HERE/../hooks" "$LEAD_DIR" "$BRANCH" "$BASE"; then
  fail "PR for $BRANCH targets $BASE, but state.json records no stack for it. Rebase onto $DEFAULT and retarget, or have the lead set stackOn and stackReason."
fi


echo "ready-push: $BRANCH, base $BASE. Running static checks..." >&2
[[ -z "$DRY" ]] || { echo "ready-push: dry run, gates passed" >&2; exit 0; }
FREE_KB=$(df -k "$REPO" | awk 'NR==2 {print $4}')
if (( FREE_KB < 3 * 1024 * 1024 )); then
  echo "ready-push: under 3 GiB free, so the static checks can't run. Pushing without them. CI will run them." >&2
else
  "$HERE/check-head.sh" "$REPO" || fail "static checks failed; fix them before pushing"
fi

# Always push HEAD to the same-named branch: a branch cut from origin/<default>
# tracks the default branch, and a bare `git push` would aim there. With no extra args,
# `printf '%q '` alone would emit `''` and git would read it as a repository.
EXTRA=""
(( $# == 0 )) || EXTRA=" $(printf '%q ' "$@")"
run "git push -u origin HEAD$EXTRA"
echo "ready-push: pushed $(run 'git rev-parse HEAD')" >&2
