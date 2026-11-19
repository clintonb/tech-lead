#!/usr/bin/env python3
"""SessionStart and UserPromptSubmit hook for tech-lead sessions.

UserPromptSubmit appends the owner's prompt to the directives ledger. SessionStart (startup, resume, compact) re-injects
the ledger and the unit list, because compaction summaries drop standing orders.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import lead_lib  # noqa: E402

NOT_HUMAN = ("<task-notification", "<teammate-message", "<agent-message", "<cross-session-message", "[Cross-session", "<system-reminder", "<local-command", "<command-",
             "This session is being continued", "Another Claude session sent a message")
INJECT_BYTES = 12_000
ROTATE_AFTER = 3
ANSWER = lead_lib.TRACKER / "answer.py"
BUILD = lead_lib.TRACKER / "build.mjs"
WAIT = lead_lib.TRACKER / "inbox-wait.sh"


def main():
    payload = lead_lib.read_input()
    if payload.get("hook_event_name") == "SessionStart":
        lead_lib.save_options()
    if lead_lib.role(payload) != lead_lib.LEAD_AGENT:
        return
    d = lead_lib.lead_dir(payload)
    event = payload.get("hook_event_name")
    if (d / "state.json").exists():
        lead_lib.ensure_watcher(d)

    if event == "UserPromptSubmit":
        prompt = (payload.get("prompt") or "").strip()
        if prompt and not prompt.startswith(NOT_HUMAN):
            with open(d / "directives.md", "a") as f:
                f.write(f"\n### {lead_lib.now_local()}\n{prompt}\n")
            for q in lead_lib.record_questions(d, prompt):
                print(f"{lead_lib.owner()} asked a question, recorded as {q['id']} in the tracker. Answer it in your reply, then record the answer in one or two sentences: "
                      f"`{ANSWER} {d} {q['id']} \"<answer>\"`. If finding out takes work, record who is finding out with `--pending \"<who and what>\"`, "
                      "and record the answer when it arrives. If it wasn't really a question, use `--drop`.")
            if lead_lib.memory_dir():
                print(f"If this message corrects you or states a lasting preference, save it as a feedback memory in {lead_lib.memory_dir()} "
                      "(one fact per file, indexed in MEMORY.md) before acting on it.")
        return

    if event == "SessionStart":
        prev_path = d / "session.json"
        prev = json.loads(prev_path.read_text()) if prev_path.exists() else {}
        compactions = prev.get("compactions", 0) if prev.get("session_id") == payload.get("session_id") else 0
        if payload.get("source") == "compact":
            compactions += 1
        prev_path.write_text(json.dumps({"transcript_path": payload.get("transcript_path"), "session_id": payload.get("session_id"), "compactions": compactions}))
        rotate = ""
        if compactions >= ROTATE_AFTER:
            rotate = (f"ROTATE NOW: this session has compacted {compactions} times. Before any other work, write a handoff "
                      f"to {d}/handoff.md, tell {lead_lib.owner()} to start a fresh lead with "
                      f"`/tech-lead:lead {d.name}` in a new session, and stop starting new work.\n\n")
        ledger = lead_lib.directives(d)
        if len(ledger) > INJECT_BYTES:
            ledger = "[older directives truncated; read the full ledger file]\n" + ledger[-INJECT_BYTES:]
        state = lead_lib.load_state(d)
        units = "\n".join(
            f"- {u['id']}: {u.get('status', '?')}, PR {u.get('pr') or '-'}, owner {u.get('owner') or '-'}, lab {u.get('lab') or 'not run'}"
            for u in (state or {}).get("units", [])
        ) or "(no state.json yet: create it before spawning workers)"
        memories = (f"save as memories any correction or lasting lesson from before this restart that isn't saved yet ({lead_lib.memory_dir()}, indexed in MEMORY.md). Then "
                    if lead_lib.memory_dir() else "")
        print(f"""{rotate}TECH-LEAD STATE ({payload.get('source')}). Lead dir: {d}
{lead_lib.owner()}'s directives, verbatim and in order. They outrank any summary of this conversation, and a later directive overrides an earlier one:
{ledger or '(none yet)'}

Units ({d}/state.json):
{units}

Tracker: {(state or {}).get('pageUrl') or (state or {}).get('pageId') or f'{d}/tracker/index.html'}. The watcher keeps it current; a hook restarts it if it dies.

Before anything else: {memories}reconcile open work against these directives, then run `node {BUILD} {d} --json`, give every orphan an owner, and start `{WAIT} {d}` with Bash run_in_background (not a Monitor, which expires).""")


if __name__ == "__main__":
    main()
