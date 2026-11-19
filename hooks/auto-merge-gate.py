#!/usr/bin/env python3
"""PreToolUse gate for subagents: the first edit on a branch whose open PR is set to auto-merge is refused once, so the agent decides whether to pause it."""
import json
import re
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import lead_lib  # noqa: E402

STATE = lead_lib.STATE / "auto-merge"
QUIET_TTL = 120  # a PR without auto-merge is rechecked after this many seconds


def run(*args, cwd=None):
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def main():
    payload = json.load(sys.stdin)
    if not payload.get("agent_type"):
        return
    path = (payload.get("tool_input") or {}).get("file_path") or (payload.get("tool_input") or {}).get("notebook_path")
    if not path:
        return
    d = pathlib.Path(path).parent
    while not d.exists() and d != d.parent:
        d = d.parent
    url = run("git", "remote", "get-url", "origin", cwd=d)
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not m:
        return
    repo = m.group(1)
    branch = run("git", "branch", "--show-current", cwd=d)
    if not branch or branch in ("master", "main"):
        return
    STATE.mkdir(parents=True, exist_ok=True)
    key = STATE / branch.replace("/", "__")
    if key.exists() and key.read_text().startswith("quiet ") and time.time() - key.stat().st_mtime < QUIET_TTL:
        return
    out = run("gh", "pr", "view", branch, "--repo", repo, "--json", "number,state,autoMergeRequest")
    try:
        pr = json.loads(out)
    except ValueError:
        return
    auto = pr.get("autoMergeRequest")
    if pr.get("state") != "OPEN" or not auto:
        key.write_text("quiet ")
        return
    seen = f"warned {auto.get('enabledAt')}"
    if key.exists() and key.read_text() == seen:
        return
    key.write_text(seen)
    n = pr["number"]
    method = (auto.get("mergeMethod") or "SQUASH").lower()
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"PR #{n} is set to auto-merge, so it merges as soon as it is green and approved, with or without the change you are starting. "
            f"If you might not push this change before that, pause it now: `gh pr merge {n} --disable-auto`, and tell the lead. "
            f"Right after your push, turn it back on: `gh pr merge {n} --auto --{method}`. "
            "If the change will be pushed within a few minutes, carry on. This warning shows once per auto-merge setting. Retry the edit."
        ),
    }}))


if __name__ == "__main__":
    main()
