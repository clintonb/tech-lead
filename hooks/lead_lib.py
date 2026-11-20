import datetime
import json
import os
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
TRACKER = ROOT / "tracker"
CONFIG_HOME = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR") or pathlib.Path.home() / ".claude")
# Personal files (config.json, checks.json, *-rules.md, pr-writing.md) and pass records. Kept outside the plugin,
# whose directory is replaced on every update.
DATA = CONFIG_HOME / "tech-lead"
STATE = DATA / "state"
LEADS = CONFIG_HOME / "leads"
PLUGIN = "tech-lead"
LEAD_AGENT = "tech-lead"
WORKER_AGENT = "pr-worker"

# userConfig keys from plugin.json with their defaults. Hooks get CLAUDE_PLUGIN_OPTION_<KEY>. Scripts run through the
# Bash tool don't, so SessionStart copies the values to DATA/config.json for them.
OPTIONS = {
    "owner_name": "the owner",
    "review_bot": "",
    "review_request": "",
    "tracker_publisher": "none",
    "push_gate": "lead",
    "prose_gate": "lead",
    "repos_dir": "~/workspace",
    "memory_dir": "",
    "lab_cli": "",
}


def _saved():
    try:
        return json.loads((DATA / "config.json").read_text())
    except (OSError, ValueError):
        return {}


def option(key):
    env = os.environ.get(f"CLAUDE_PLUGIN_OPTION_{key.upper()}")
    if env is not None:
        return env
    return _saved().get(key, OPTIONS[key])


def save_options():
    values = {k: os.environ[f"CLAUDE_PLUGIN_OPTION_{k.upper()}"] for k in OPTIONS if f"CLAUDE_PLUGIN_OPTION_{k.upper()}" in os.environ}
    if not values or values == _saved():
        return
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = DATA / "config.json.tmp"
    tmp.write_text(json.dumps(values, indent=1))
    tmp.replace(DATA / "config.json")


def owner():
    return option("owner_name") or OPTIONS["owner_name"]


def memory_dir():
    m = option("memory_dir").strip()
    return pathlib.Path(m).expanduser() if m else None


def bare(kind):
    """Agent type without the plugin prefix: `tech-lead:pr-worker` and `pr-worker` are the same role."""
    return kind.split(":", 1)[1] if kind and kind.startswith(PLUGIN + ":") else kind


BRIEF_UNIT = re.compile(r"^UNIT:\s*(\S+)\s*$", re.M)
BRIEF_LEAD_DIR = re.compile(r"^LEAD_DIR:\s*(\S+)\s*$", re.M)


def read_input():
    import sys
    return json.load(sys.stdin)


SESSIONS = LEADS / ".sessions"


def session_project(payload):
    """The project `/lead` recorded for this main session, or None."""
    sid = (payload or {}).get("session_id")
    p = SESSIONS / sid if sid else None
    return (p.read_text().strip() or None) if p and p.is_file() else None


def role(payload):
    """agent_type for --agent sessions, subagents and teammates; tech-lead for a main session switched with `/lead`."""
    kind = bare((payload or {}).get("agent_type"))
    if kind:
        return kind
    return LEAD_AGENT if session_project(payload) else None


def lead_dir(payload=None):
    project = os.environ.get("LEAD_PROJECT") or session_project(payload) or pathlib.Path((payload or {}).get("cwd") or os.getcwd()).name
    d = LEADS / project
    d.mkdir(parents=True, exist_ok=True)
    return d


def now_local():
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")


def load_state(d):
    p = pathlib.Path(d) / "state.json"
    return json.loads(p.read_text()) if p.exists() else None


def directives(d):
    p = pathlib.Path(d) / "directives.md"
    return p.read_text() if p.exists() else ""


def allowed(d, kind, branch):
    """True when the owner wrote `allow-<kind> <branch>` in a directive. Only human prompts reach the ledger."""
    return re.search(rf"(?im)^.*\ballow-{kind}\s+{re.escape(branch)}\b", directives(d)) is not None


def stack_allowed(d, branch, base=None):
    """True when the owner wrote `allow-stack <branch>`, or the lead recorded the stack in state.json with stackOn and stackReason."""
    if allowed(d, "stack", branch):
        return True
    for u in (load_state(d) or {}).get("units", []):
        if u.get("branch") == branch and u.get("stackOn") and (u.get("stackReason") or "").strip():
            return base is None or base == u["stackOn"]
    return False


def first_user_text(transcript_path):
    try:
        with open(transcript_path) as f:
            for line in f:
                row = json.loads(line)
                if row.get("type") != "user":
                    continue
                c = row["message"]["content"]
                if isinstance(c, list):
                    c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
                return c
    except (OSError, ValueError, KeyError):
        pass
    return ""


def brief_unit(text):
    u, d = BRIEF_UNIT.search(text or ""), BRIEF_LEAD_DIR.search(text or "")
    return (u.group(1) if u else None, d.group(1) if d else None)


def find_unit(state, unit_id):
    return next((u for u in (state or {}).get("units", []) if u.get("id") == unit_id), None)


def pr_state(repo, ref):
    out = subprocess.run(
        ["node", str(TRACKER / "pr-state.mjs"), "--repo", repo, str(ref)],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(out.stderr.strip() or "pr-state.mjs printed nothing")
    return json.loads(out.stdout.strip().splitlines()[0])


def tracker_json(d):
    out = subprocess.run(
        ["node", str(TRACKER / "build.mjs"), str(d), "--json"],
        capture_output=True, text=True, timeout=120,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return json.loads(out.stdout)


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason,
    }}))


QUESTION_SPLIT = re.compile(r"(?<=[.?!])\s+|\n+")


def load_questions(d):
    p = pathlib.Path(d) / "questions.json"
    return json.loads(p.read_text()) if p.exists() else []


def save_questions(d, qs):
    p = pathlib.Path(d) / "questions.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(qs, indent=1))
    tmp.replace(p)


def record_questions(d, prompt):
    """Adds the question sentences of one of the owner's prompts to questions.json. Returns the new entries."""
    if "?" not in prompt:
        return []
    asked = [s.strip() for s in QUESTION_SPLIT.split(prompt) if s.strip().endswith("?")]
    text = " ".join(asked) if asked else prompt.strip()
    if len(text) > 600:
        text = text[:600] + "..."
    qs = load_questions(d)
    q = {"id": f"q{len(qs) + 1}", "asked": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
         "text": text, "status": "open"}
    qs.append(q)
    save_questions(d, qs)
    return [q]


def default_branch(cwd):
    """The repo's default branch at cwd."""
    try:
        out = subprocess.run([str(BIN / "default-branch.sh"), cwd or "."],
                             capture_output=True, text=True, timeout=20).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        out = ""
    return out or "master"


def ensure_watcher(d):
    """Starts the tracker watcher for lead dir d unless one is running. It rebuilds the tracker every minute and publishes it when a publisher is set."""
    if os.environ.get("TECH_LEAD_NO_WATCHER"):
        return False
    d = str(d).rstrip("/")
    running = subprocess.run(["pgrep", "-f", f"^node .*build.mjs {d} --watch"], capture_output=True, text=True).stdout.strip()
    if running:
        return False
    log = open(f"{d}/watcher.log", "a")
    subprocess.Popen(["node", str(TRACKER / "build.mjs"), d, "--watch", "--publish"], stdout=log, stderr=log,
                     stdin=subprocess.DEVNULL, start_new_session=True)
    return True


def declared_checks(repo):
    """True when check-head.sh can find the repo's static checks."""
    r = pathlib.Path(repo)
    if (r / "package.json").is_file():
        try:
            scripts = json.loads((r / "package.json").read_text()).get("scripts") or {}
        except ValueError:
            scripts = {}
        if "lint:strict:changed" in scripts or "check" in scripts:
            return True
    return any(os.access(r / "scripts" / n, os.X_OK) for n in ("check", "lint"))


def own_transcript(payload):
    """The calling subagent's transcript, which starts with its brief. Empty for a main session."""
    if payload.get("agent_transcript_path"):
        return payload["agent_transcript_path"]
    aid, main = payload.get("agent_id"), payload.get("transcript_path")
    if not aid or not main:
        return ""
    return str(pathlib.Path(main).with_suffix("") / "subagents" / f"agent-{aid}.jsonl")
