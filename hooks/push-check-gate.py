#!/usr/bin/env python3
"""PreToolUse gate: a git push from a repo that declares static checks needs check-head.sh to have passed on the commit.

The push_gate setting picks where it applies: every session (all), lead and worker sessions (lead), or nowhere (off).
"""
import json
import pathlib
import re
import shlex
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import lead_lib  # noqa: E402

MARKS = lead_lib.STATE / "checks"
MIN_FREE = 3 * 1024**3  # typecheck and lint fail with ENOSPC below this, so the checks can't run
PUSH = re.compile(r"\bgit\s+(?:-C\s+(\S+)\s+)?push\b([^;&|]*)")
CD = re.compile(r"(?:^|[;&|]\s*)cd\s+(\S+)\s*(?:&&|;)")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=10).stdout.strip()


def main():
    payload = json.load(sys.stdin)
    if payload.get("tool_name") != "Bash":
        return
    scope = lead_lib.option("push_gate")
    if scope == "off" or (scope == "lead" and lead_lib.role(payload) not in (lead_lib.LEAD_AGENT, lead_lib.WORKER_AGENT)):
        return
    cmd = payload.get("tool_input", {}).get("command", "")
    m = PUSH.search(cmd)
    lab = lead_lib.option("lab_cli").strip()
    if not m or (lab and re.search(rf"\b{re.escape(lab)}\s+ssh\b", cmd)):
        return
    args = m.group(2)
    if re.search(r"(--delete|--tags|--dry-run|(^|\s)-[dn](\s|$))", args):
        return
    cds = CD.findall(cmd[: m.start()])
    repo = pathlib.Path(payload.get("cwd") or ".")
    for d in cds:
        repo = repo / pathlib.Path(shlex.split(d)[0]).expanduser()
    if m.group(1):
        repo = repo / pathlib.Path(m.group(1)).expanduser()
    repo = str(repo)
    top = git(repo, "rev-parse", "--show-toplevel")
    if not top or not lead_lib.declared_checks(top):
        return
    explicit = re.search(r"\s([0-9a-f]{7,40}):", args)
    sha = git(repo, "rev-parse", explicit.group(1) if explicit else "HEAD")
    if sha and not (MARKS / sha).exists() and shutil.disk_usage(repo).free < MIN_FREE:
        print(json.dumps({"systemMessage": f"push-check-gate: the disk is nearly full, so {sha[:8]} was pushed without local static checks. CI will run them."}))
        return
    if sha and not (MARKS / sha).exists():
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": f"{sha[:8]} has not passed the static checks. Run `check-head.sh {repo}`, fix what it reports, then push.",
        }}))


if __name__ == "__main__":
    main()
