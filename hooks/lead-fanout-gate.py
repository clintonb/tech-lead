#!/usr/bin/env python3
"""PreToolUse gate on Agent calls from a tech-lead session.

Code goes to pr-worker agents only, each brief names one unit in state.json, stacks only where state.json
records stackOn and stackReason for the unit, and no new unit starts while an open red PR has no live owner.
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import lead_lib  # noqa: E402

READ_ONLY_AGENTS = {"Explore", "prose-judge", "claude-code-guide"}
MAX_BRIEF_LINES = 40
STACK_HINT = re.compile(r"(--base\s+(?!(?:master|main)\b)\S+|from\s+`?origin/(?!(?:master|main)\b)[\w./-]+)")


def main():
    payload = lead_lib.read_input()
    if lead_lib.role(payload) != lead_lib.LEAD_AGENT or payload.get("tool_name") != "Agent":
        return
    if (lead_lib.lead_dir(payload) / "state.json").exists():
        lead_lib.ensure_watcher(lead_lib.lead_dir(payload))
    args = payload.get("tool_input", {})
    kind = lead_lib.bare(args.get("subagent_type") or "general-purpose")
    if kind in READ_ONLY_AGENTS:
        return
    if kind != lead_lib.WORKER_AGENT:
        return lead_lib.deny(f"A lead hands work only to `{lead_lib.PLUGIN}:{lead_lib.WORKER_AGENT}` agents, which carry the stop gate. Use subagent_type `{lead_lib.PLUGIN}:{lead_lib.WORKER_AGENT}` (or Explore for read-only questions).")

    brief = args.get("prompt", "")
    unit_id, dir_ = lead_lib.brief_unit(brief)
    d = lead_lib.lead_dir(payload)
    if not unit_id or not dir_:
        return lead_lib.deny(f"The brief must start with `UNIT: <id>` and `LEAD_DIR: {d}` lines. Use {lead_lib.ROOT}/skills/tech-lead/brief-template.md.")
    state = lead_lib.load_state(dir_)
    unit = lead_lib.find_unit(state, unit_id)
    if not unit:
        return lead_lib.deny(f"Unit `{unit_id}` is not in {dir_}/state.json. Add it there first.")
    lines = len(brief.strip().splitlines())
    if lines > MAX_BRIEF_LINES:
        return lead_lib.deny(f"The brief is {lines} lines; the limit is {MAX_BRIEF_LINES}. State the behavior in five bullets and link the shared rules file instead of inlining them.")
    stack = STACK_HINT.search(brief)
    if stack and not lead_lib.stack_allowed(dir_, unit.get("branch", "")):
        return lead_lib.deny(f"The brief stacks the branch (`{stack.group(0)}`). Branch from the default branch, or record the stack first: set stackOn and stackReason on unit {unit_id} in state.json, following the stacking order in the tech-lead skill.")

    try:
        view = lead_lib.tracker_json(dir_)
    except Exception as e:
        print(f"lead-fanout-gate: tracker failed ({e}); allowing spawn", file=sys.stderr)
        return
    orphans = [o for o in view["orphans"] if o.get("number") != unit.get("pr")]
    if orphans:
        listing = "\n".join(f"- #{o['number']} owner {o.get('owner') or 'none'}: {'; '.join(o['actions'])}" for o in orphans)
        return lead_lib.deny(f"These red PRs have no running owner. Resume their owners (SendMessage) or spawn a pr-worker for their unit before starting `{unit_id}`:\n{listing}")


if __name__ == "__main__":
    main()
