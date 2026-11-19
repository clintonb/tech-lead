#!/usr/bin/env python3
"""SubagentStop and TeammateIdle gate for pr-worker agents: a worker may not stop while its PR is red.

Waiting (static checks or review still running), yellow and green are allowed, and the lead's orphan sweep resumes
the worker if a late check turns the PR red. Fails open on GitHub errors so a flaky API never traps a worker.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import lead_lib  # noqa: E402


EVENT = {}
LOG = lead_lib.LEADS / "stop-gate.log"


def block(reason):
    with open(LOG, "a") as f:
        f.write(f"{lead_lib.now_local()} {EVENT.get('hook_event_name')} {EVENT.get('teammate_name') or EVENT.get('agent_type')}: BLOCK {reason.splitlines()[0]}\n")
    if EVENT.get("hook_event_name") == "TeammateIdle":
        print(reason, file=sys.stderr)
        sys.exit(2)
    print(json.dumps({"decision": "block", "reason": reason}))


def teammate_transcript(payload):
    """TeammateIdle carries no transcript path; teammates write under the lead session's subagents directory."""
    lead = pathlib.Path(payload.get("transcript_path", ""))
    name = payload.get("teammate_name") or ""
    found = sorted((lead.parent / lead.stem / "subagents").glob(f"agent-a{name}-*.jsonl"), key=lambda p: p.stat().st_mtime)
    return str(found[-1]) if found else ""


def main():
    payload = lead_lib.read_input()
    EVENT.update(payload)
    if payload.get("hook_event_name") == "TeammateIdle":
        path = teammate_transcript(payload)
    elif lead_lib.role(payload) == lead_lib.WORKER_AGENT:
        path = payload.get("agent_transcript_path", "")
    else:
        return
    unit_id, dir_ = lead_lib.brief_unit(lead_lib.first_user_text(path))
    if not unit_id or not dir_:
        return
    d = pathlib.Path(dir_)
    state = lead_lib.load_state(d)
    name = payload.get("teammate_name")
    owned = [u for u in (state or {}).get("units", []) if u.get("id") == unit_id or (name and u.get("owner") == name)]
    blockers = []
    for unit in owned:
        if unit.get("kind") == "lab" or unit.get("status") in ("dropped", "merged", "paused"):
            continue
        ref = unit.get("pr") or unit.get("branch")
        if not ref:
            blockers.append(f"Unit {unit['id']} has no branch in {d}/state.json. Ask the lead to set it, then open the draft PR against the default branch.")
            continue
        try:
            pr = lead_lib.pr_state(state["repo"], ref)
        except Exception as e:
            print(f"worker-stop-gate: could not read PR state for {ref} ({e}); skipping it", file=sys.stderr)
            continue
        if pr["state"] == "none":
            blockers.append(f"No open PR for {ref}. Push through ready-push.sh and open the draft PR against the default branch.")
        elif pr["state"] == "red":
            blockers.append(f"PR #{pr['number']} is red:\n  - " + "\n  - ".join(pr["actions"]))
    if blockers:
        request = f"comment `{lead_lib.option('review_request')}`, " if lead_lib.option("review_request") else ""
        block(
            "You own PRs that are not ready, so you cannot stop yet. Work them in this order: push a rebase that resolves a "
            "conflict first, then CI failures, then review threads. Push through ready-push.sh, " + request +
            "and reply to and resolve every thread by ID.\n- " + "\n- ".join(blockers)
        )

if __name__ == "__main__":
    main()
