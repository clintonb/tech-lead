#!/usr/bin/env python3
"""PreToolUse gate for pr-worker agents and the tech-lead.

Workers push only through ready-push.sh and open draft PRs against the repo's default branch. The lead never pushes or opens PRs,
and writes files only under its lead directory or the session scratchpad.
"""
import pathlib
import re
import shlex
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import lead_lib  # noqa: E402

GIT_PUSH = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?push\b")
PR_CREATE = re.compile(r"\bgh\s+pr\s+create\b")
DEV_WORK = re.compile(r"\b(typecheck|tsc|lint|check-format|prettier|format|jest|test|compile|git\s+(push|rebase|commit|merge|cherry-pick))\b")
PARK_WHO = "|".join(re.escape(w) for w in {"me", "his", "her", "their", "the owner", lead_lib.owner().lower()})
PARK = re.compile(rf"\b(you can stop|stop until|stop for now|hold (off|the push)|keep holding|wait (for|on|until) ({PARK_WHO})|until (you hear back|{PARK_WHO}))\b", re.I)
THREAD_REPLY = re.compile(r"(say\.sh|/replies\b|resolveReviewThread)")
PR_RETITLE = re.compile(r"\bgh\s+pr\s+edit\b.*\s--(title|body|body-file)\b")


def arg(tokens, name):
    for i, t in enumerate(tokens):
        if t == name and i + 1 < len(tokens):
            return tokens[i + 1]
        if t.startswith(name + "="):
            return t.split("=", 1)[1]
    return None


def main():
    payload = lead_lib.read_input()
    role = lead_lib.role(payload)
    tool = payload.get("tool_name")
    if role == lead_lib.LEAD_AGENT and tool in ("Write", "Edit"):
        path = str(pathlib.Path(payload.get("tool_input", {}).get("file_path", "")).resolve())
        allowed = [str(lead_lib.LEADS.resolve()), str((lead_lib.CONFIG_HOME / "plans").resolve()), "/private/tmp/", "/tmp/"]
        if lead_lib.memory_dir():
            allowed.append(str(lead_lib.memory_dir().resolve()))
        if not path.startswith(tuple(allowed)):
            return lead_lib.deny(f"The lead writes only its own state under {lead_lib.LEADS} or the scratchpad. Code changes go to a pr-worker.")
        return
    command = payload.get("tool_input", {}).get("command", "") if tool == "Bash" else ""
    lab = lead_lib.option("lab_cli").strip()
    if role and lab and re.search(rf"(^|[\s;&|(`$]){re.escape(lab)}\s+[a-z]", command) and DEV_WORK.search(command):
        return lead_lib.deny(f"`{lab}` is for lab runs only. Typecheck, lint, format, specs, commits, rebases and pushes run in the local worktree.")
    if role == lead_lib.LEAD_AGENT and tool == "SendMessage":
        return park_gate(payload)
    if tool != "Bash" or role not in (lead_lib.WORKER_AGENT, lead_lib.LEAD_AGENT):
        return
    cmd = payload.get("tool_input", {}).get("command", "")

    if role == lead_lib.LEAD_AGENT:
        if GIT_PUSH.search(cmd) or PR_CREATE.search(cmd) or "ready-push.sh" in cmd:
            return lead_lib.deny("The lead does not push or open PRs. Send the work to the unit's pr-worker.")
        if THREAD_REPLY.search(cmd):
            return lead_lib.deny("The PR's owner replies to and resolves its own threads. Send the finding to the owner and let it fix, reply and resolve.")
        return

    if GIT_PUSH.search(cmd) and "ready-push.sh" not in cmd:
        return lead_lib.deny("Push only through `ready-push.sh <repo> <lead-dir> [--force-with-lease]`. It runs the static checks and the base gate first.")
    if PR_RETITLE.search(cmd):
        return lead_lib.deny("Workers do not edit a PR title or body after opening it. Send the proposed text to the lead.")
    if PR_CREATE.search(cmd):
        try:
            tokens = shlex.split(cmd[PR_CREATE.search(cmd).start():].split("&&")[0])
        except ValueError:
            tokens = cmd.split()
        default = lead_lib.default_branch(payload.get("cwd"))
        base = arg(tokens, "--base") or arg(tokens, "-B") or default
        if "--draft" not in tokens and "-d" not in tokens:
            return lead_lib.deny("Open the PR as a draft (`--draft`).")
        if base != default:
            head = arg(tokens, "--head") or arg(tokens, "-H") or ""
            d = lead_lib.lead_dir(payload)
            if not (head and lead_lib.stack_allowed(d, head, base)):
                return lead_lib.deny(f"PRs target {default} unless the lead recorded this stack: the unit for `{head}` in state.json needs stackOn `{base}` and a stackReason. Pass --head explicitly.")


def park_gate(payload):
    """A red PR is never parked: the lead may not tell its owner to stop or wait while it is red."""
    tool_input = payload.get("tool_input", {})
    message = tool_input.get("message")
    if not isinstance(message, str) or not PARK.search(message):
        return
    d = lead_lib.lead_dir(payload)
    state = lead_lib.load_state(d) or {}
    for unit in state.get("units", []):
        if unit.get("owner") != tool_input.get("to") or unit.get("status") in ("paused", "merged", "dropped") or not unit.get("pr"):
            continue
        try:
            pr = lead_lib.pr_state(state["repo"], unit["pr"])
        except Exception:
            continue
        if pr["state"] == "red":
            return lead_lib.deny(
                f"#{pr['number']} is red ({'; '.join(pr['actions'])}). Its owner keeps working until it is not. "
                f"Send the blockers to fix instead. P0, P1 and data-affecting findings get fixed. Other P2s get declined with a bound, not escalated to {lead_lib.owner()}. "
                f"If {lead_lib.owner()} didn't ask for this PR or parked it, set the unit's status to paused or dropped in {d}/state.json first, then tell the owner to stop."
            )


if __name__ == "__main__":
    main()
