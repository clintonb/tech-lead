#!/usr/bin/env python3
"""PreToolUse gate: a PR title or body reaches GitHub only after prose-check.py passed that exact text.

The prose_gate setting picks where it applies: every session (all), lead and worker sessions (lead), or nowhere (off).
"""
import json
import pathlib
import re
import shlex
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import lead_lib  # noqa: E402
from importlib.machinery import SourceFileLoader  # noqa: E402

check = SourceFileLoader("prose_check", str(lead_lib.BIN / "prose-check.py")).load_module()

PR_WRITE = re.compile(r"(?:^|[;&|(]|\n)\s*gh\s+pr\s+(create|edit)\b")
MCP_WRITE = re.compile(r"^mcp__.*github__(create_pull_request|update_pull_request)$")
HOW = "Run `prose-check.py --title \"<title>\" --body-file <file>` on the exact text, fix what it reports, then retry with that same text."


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason,
    }}))


def arg(tokens, *names):
    for i, t in enumerate(tokens):
        for n in names:
            if t == n and i + 1 < len(tokens):
                return tokens[i + 1]
            if t.startswith(n + "="):
                return t.split("=", 1)[1]
    return None


def unchecked(cwd, title, body, body_file):
    missing = []
    if title is not None and not (check.MARKS / check.digest("title", title)).exists():
        missing.append("title")
    if body_file is not None:
        path = pathlib.Path(body_file).expanduser()
        path = path if path.is_absolute() else pathlib.Path(cwd) / path
        try:
            body = path.read_text()
        except OSError:
            return [f"body file {body_file} (unreadable)"]
    if body is not None and not (check.MARKS / check.digest("body", body)).exists():
        missing.append("body")
    return missing


def main():
    payload = json.load(sys.stdin)
    tool = payload.get("tool_name", "")
    data = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or "."
    scope = lead_lib.option("prose_gate")
    if scope == "off" or (scope == "lead" and lead_lib.role(payload) not in (lead_lib.LEAD_AGENT, lead_lib.WORKER_AGENT)):
        return
    if tool == "Bash" and re.search(r"tech-lead/state/prose(/|\s|$)", data.get("command", "")) and "prose-check.py" not in data.get("command", ""):
        return deny("Only prose-check.py records prose passes.")
    if tool == "Bash" and "prose-check.py" in data.get("command", "") and re.search(r"--approve\b", data["command"]):
        return deny(f"Only {lead_lib.owner()} approves PR text past the judge. Ask them to type `! {lead_lib.BIN}/prose-check.py --approve --title ... --body-file ...` themselves.")
    if tool == "Bash":
        m = PR_WRITE.search(data.get("command", ""))
        if not m:
            return
        try:
            tokens = shlex.split(data["command"][m.start(1) - len("gh pr "):].split("&&")[0].split(";")[0])
        except ValueError:
            return deny("Couldn't parse this PR command. Put the body in a file and pass --title and --body-file plainly.")
        title, body, body_file = arg(tokens, "--title", "-t"), arg(tokens, "--body", "-b"), arg(tokens, "--body-file", "-F")
        if m.group(1) == "create" and (title is None or (body is None and body_file is None)):
            return deny("Open PRs with an explicit --title and --body-file, both checked by prose-check.py. " + HOW)
    elif MCP_WRITE.match(tool):
        title, body, body_file = data.get("title"), data.get("body"), None
    else:
        return
    missing = unchecked(cwd, title, body, body_file)
    if missing:
        deny(f"The PR {' and '.join(missing)} {'have' if len(missing) > 1 else 'has'} not passed the prose judge. " + HOW)


if __name__ == "__main__":
    main()
