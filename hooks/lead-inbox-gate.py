#!/usr/bin/env python3
"""Stop gate for tech-lead sessions: every question the owner asked has a recorded answer or owner, and inbox-wait.sh watches the inbox, so watcher lines always wake the lead."""
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import lead_lib  # noqa: E402

WAIT = lead_lib.TRACKER / "inbox-wait.sh"
ANSWER = lead_lib.TRACKER / "answer.py"


def alive(pidfile):
    try:
        os.kill(int(pidfile.read_text().strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def unread(inbox):
    log, off = inbox / "lead.log", inbox / ".lead.offset"
    if not log.exists():
        return ""
    data = log.read_bytes()
    try:
        seen = int(off.read_text().strip())
    except (OSError, ValueError):
        seen = 0
    seen = 0 if seen > len(data) else seen
    off.write_text(str(len(data)))
    return data[seen:].decode(errors="replace").strip()


def main():
    payload = lead_lib.read_input()
    if lead_lib.role(payload) != lead_lib.LEAD_AGENT or payload.get("stop_hook_active"):
        return
    d = lead_lib.lead_dir(payload)
    # The lead just worked, so a watcher that paused for lack of work starts again.
    if (d / "state.json").exists():
        lead_lib.ensure_watcher(d)
    unanswered = [q for q in lead_lib.load_questions(d) if q["status"] == "open"]
    if unanswered:
        listing = "\n".join(f"- {q['id']}: {q['text']}" for q in unanswered)
        return print(json.dumps({"decision": "block", "reason": (
            f"{lead_lib.owner()}'s questions have no recorded answer:\n{listing}\n\nFor each one, record the answer you gave in one or two sentences with "
            f"`{ANSWER} {d} <id> \"<answer>\"`. If someone is still finding out, use `--pending \"<who and what>\"`, and record the answer when it arrives. "
            f"Use `--drop` for one that wasn't really a question. The tracker shows these to {lead_lib.owner()}.")}))
    inbox = d / "inbox"
    if alive(inbox / ".lead.waiter"):
        return
    lines = unread(inbox)
    reason = f"Nothing is watching your inbox, so watcher lines would sit unread while you are idle. Start `{WAIT} {d}` with Bash run_in_background before ending the turn. It exits on the next inbox line, which wakes you. Act on that line, then start it again. Don't use a Monitor for this: Monitors expire after 30 minutes."
    if lines:
        reason = f"Unread inbox lines. Act on every ORPHAN and OVERLOADED line first:\n{lines[-4000:]}\n\n" + reason
    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    main()
