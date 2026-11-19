#!/usr/bin/env bash
# Feeds recorded tool calls to the hooks and checks each decision. The orphan and stop tests read live PR state, so they
# need an open red PR and a merged PR of yours in TEST_REPO.
# Usage: TEST_REPO=owner/name TEST_MERGED_PR=<n> tests/run.sh
set -uo pipefail
REPO="${TEST_REPO:?set TEST_REPO=owner/name}"; MERGED="${TEST_MERGED_PR:?set TEST_MERGED_PR to a merged PR number in TEST_REPO}"
ROOT=$(cd "$(dirname "$0")/.." && pwd); H="$ROOT/hooks"; T=$(mktemp -d); PASS=0; FAILN=0
# Leads, pass records and the copied settings all live under CLAUDE_CONFIG_DIR, so the run can't touch real ones.
export CLAUDE_CONFIG_DIR="$T/config"
export CLAUDE_PLUGIN_OPTION_OWNER_NAME="Pat" CLAUDE_PLUGIN_OPTION_LAB_CLI="coder" CLAUDE_PLUGIN_OPTION_PROSE_GATE="all" CLAUDE_PLUGIN_OPTION_PUSH_GATE="all"
export LEAD_PROJECT="harness-test"; LD="$CLAUDE_CONFIG_DIR/leads/$LEAD_PROJECT"; mkdir -p "$LD"
trap 'rm -rf "$T"' EXIT
check() {
  local out; out=$(printf '%s' "$4" | python3 "$H/$3" 2>/dev/null)
  local got=allow; grep -q '"permissionDecision": "deny"' <<<"$out" && got=deny; grep -q '"decision": "block"' <<<"$out" && got=block
  if [[ "$got" == "$2" ]]; then PASS=$((PASS+1)); echo "ok   $1"; else FAILN=$((FAILN+1)); echo "FAIL $1 (expected $2, got $got) ${out:0:200}"; fi
}
pre() { python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","agent_type":sys.argv[1],"tool_name":sys.argv[2],"tool_input":json.loads(sys.argv[3]),"cwd":"/tmp"}))' "$@"; }
spawn() { python3 -c 'import json,sys; print(json.dumps({"subagent_type":sys.argv[1],"prompt":sys.argv[2]}))' "$@"; }
mk() { python3 -c 'import json,sys; print(json.dumps({"type":"user","message":{"role":"user","content":sys.argv[1]}}))' "$1" > "$T/$2.jsonl"; echo "$T/$2.jsonl"; }
stop() { python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"SubagentStop","agent_type":sys.argv[1],"agent_transcript_path":sys.argv[2],"stop_hook_active":False}))' "$@"; }

RED_PR=""
for n in $(gh pr list --repo "$REPO" --author @me --state open --limit 50 --json number --jq '.[].number'); do
  if [[ "$(node "$ROOT/tracker/pr-state.mjs" --repo "$REPO" "$n" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')" == red ]]; then RED_PR=$n; break; fi
done
[[ -n "$RED_PR" ]] || { echo "no red PR of yours is open in $REPO; the orphan and stop tests need one"; exit 2; }
echo "using red PR #$RED_PR"
cat > "$LD/state.json" <<J
{"title":"t","repo":"$REPO","branchPrefixes":[],"units":[
 {"id":"red","pr":$RED_PR,"owner":"w-red"},
 {"id":"merged","pr":$MERGED,"owner":"w-m"},
 {"id":"fresh","branch":"me/new-feature","owner":null},
 {"id":"stacked","branch":"me/on-base","owner":null,"stackOn":"me/shared-base","stackReason":"Uses the shared base class from the base PR."}]}
J

PRC="gh pr"" create"
CODE='{"file_path":"/opt/repo/src/x.ts"}'
for W in pr-worker tech-lead:pr-worker; do
  check "$W raw git push" deny role-gate.py "$(pre $W Bash '{"command":"git push --force-with-lease"}')"
done
check "worker pushes through the lab CLI" deny role-gate.py "$(pre pr-worker Bash '{"command":"coder ssh ws -- bash -lc \"cd repo && git push\""}')"
check "worker ready-push" allow role-gate.py "$(pre pr-worker Bash '{"command":"ready-push.sh ~/repo ~/.claude/leads/x --force-with-lease"}')"
check "unrecorded stacked PR" deny role-gate.py "$(pre pr-worker Bash "{\"command\":\"$PRC --draft --base me/other-feature --body-file b.md --title x\"}")"
check "non-draft PR" deny role-gate.py "$(pre pr-worker Bash "{\"command\":\"$PRC --body-file b.md --title x\"}")"
check "recorded stack on its base" allow role-gate.py "$(pre pr-worker Bash "{\"command\":\"$PRC --draft --base me/shared-base --head me/on-base --body-file b.md --title x\"}")"
check "recorded stack on the wrong base" deny role-gate.py "$(pre pr-worker Bash "{\"command\":\"$PRC --draft --base me/other --head me/on-base --body-file b.md --title x\"}")"
check "draft PR on the default branch" allow role-gate.py "$(pre pr-worker Bash "{\"command\":\"$PRC --draft --body-file b.md --title x\"}")"
check "worker retitles PR" deny role-gate.py "$(pre pr-worker Bash '{"command":"gh pr edit 1234 --title y"}')"
check "lead git push" deny role-gate.py "$(pre tech-lead Bash '{"command":"git push"}')"
check "lead edits repo code" deny role-gate.py "$(pre tech-lead Edit "$CODE")"
check "lead writes its state" allow role-gate.py "$(pre tech-lead Write "{\"file_path\":\"$LD/state.json\"}")"
check "lead lists PRs" allow role-gate.py "$(pre tech-lead Bash '{"command":"gh pr list --author @me"}')"
check "non-lead session untouched" allow role-gate.py "$(pre "" Bash '{"command":"git push"}')"

check "lead spawns general-purpose with a stacked brief" deny lead-fanout-gate.py "$(pre tech-lead Agent "$(spawn general-purpose 'Your branch is `me/next`, from `origin/me/other-feature` (#1234).')")"
check "pr-worker brief without UNIT" deny lead-fanout-gate.py "$(pre tech-lead Agent "$(spawn tech-lead:pr-worker 'Build the vendor loader.')")"
check "stacked brief" deny lead-fanout-gate.py "$(pre tech-lead Agent "$(spawn tech-lead:pr-worker "UNIT: fresh
LEAD_DIR: $LD
Branch from origin/me/other-feature")")"
check "new unit while an orphan exists" deny lead-fanout-gate.py "$(pre tech-lead Agent "$(spawn tech-lead:pr-worker "UNIT: fresh
LEAD_DIR: $LD
Branch from the default branch")")"
for W in pr-worker tech-lead:pr-worker; do
  check "re-owning the orphan as $W" allow lead-fanout-gate.py "$(pre tech-lead Agent "$(spawn $W "UNIT: red
LEAD_DIR: $LD
Fix the blockers")")"
done
check "lead parks a red PR" deny role-gate.py "$(pre tech-lead SendMessage '{"to":"w-red","message":"Waiting on Pat. Stop until you hear back."}')"
check "lead routes blockers to a red PR" allow role-gate.py "$(pre tech-lead SendMessage '{"to":"w-red","message":"Fix the two threads, push, reply and resolve."}')"
check "lead posts thread replies" deny role-gate.py "$(pre tech-lead Bash '{"command":"say.sh 1234 PRRT_x Declining"}')"
check "PR text the judge never passed" deny pr-prose-gate.py "$(pre "" Bash "{\"command\":\"$PRC --draft --title 'feat: x' --body 'This PR introduces y'\"}")"
check "PR without explicit text" deny pr-prose-gate.py "$(pre "" Bash "{\"command\":\"$PRC --draft --fill\"}")"
check "PR wording inside a script is not a PR" allow pr-prose-gate.py "$(pre "" Bash "$(python3 -c 'import json,sys; print(json.dumps({"command": "python3 -c \x27print(\"refuses " + sys.argv[1] + " until\")\x27"}))' "$PRC")")"
CLAUDE_PLUGIN_OPTION_PROSE_GATE=off check "prose gate off" allow pr-prose-gate.py "$(pre "" Bash "{\"command\":\"$PRC --draft --fill\"}")"
check "Explore always allowed" allow lead-fanout-gate.py "$(pre tech-lead Agent "$(spawn Explore 'find x')")"

check "lead idles with nothing watching its inbox" block lead-inbox-gate.py '{"hook_event_name":"Stop","agent_type":"tech-lead","stop_hook_active":false,"cwd":"/tmp"}'
echo '[{"id":"q1","asked":"2026-11-15T00:00:00+00:00","text":"Does the export include refunds?","status":"open"}]' > "$LD/questions.json"
check "lead idles with an unanswered question" block lead-inbox-gate.py '{"hook_event_name":"Stop","agent_type":"tech-lead","stop_hook_active":false,"cwd":"/tmp"}'
if grep -q "include refunds" <<<"$(printf '%s' '{"hook_event_name":"Stop","agent_type":"tech-lead","stop_hook_active":false,"cwd":"/tmp"}' | python3 "$H/lead-inbox-gate.py")"; then PASS=$((PASS+1)); echo "ok   stop gate lists the open question"; else FAILN=$((FAILN+1)); echo "FAIL stop gate lists the open question"; fi
rm "$LD/questions.json"
check "worker stop is not the lead inbox gate" allow lead-inbox-gate.py '{"hook_event_name":"Stop","agent_type":"pr-worker","stop_hook_active":false,"cwd":"/tmp"}'
for W in pr-worker tech-lead:pr-worker; do
  check "$W stops with red PR #$RED_PR" block worker-stop-gate.py "$(stop $W "$(mk "UNIT: red
LEAD_DIR: $LD
go" red)")"
done
check "worker stops after merge" allow worker-stop-gate.py "$(stop tech-lead:pr-worker "$(mk "UNIT: merged
LEAD_DIR: $LD
go" merged)")"
check "worker stops with no PR opened" block worker-stop-gate.py "$(stop tech-lead:pr-worker "$(mk "UNIT: fresh
LEAD_DIR: $LD
go" fresh)")"
check "other subagent types unaffected" allow worker-stop-gate.py "$(stop Explore "$(mk "UNIT: red
LEAD_DIR: $LD" ex)")"

SID="harness-test-sid"; mkdir -p "$CLAUDE_CONFIG_DIR/leads/.sessions"; echo "$LEAD_PROJECT" > "$CLAUDE_CONFIG_DIR/leads/.sessions/$SID"
pres() { python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","session_id":sys.argv[1],"agent_type":sys.argv[2] or None,"tool_name":sys.argv[3],"tool_input":json.loads(sys.argv[4]),"cwd":"/tmp"}))' "$@"; }
check "/lead session edits repo code" deny role-gate.py "$(pres "$SID" "" Edit "$CODE")"
check "/lead session writes its plan" allow role-gate.py "$(pres "$SID" "" Write "{\"file_path\":\"$CLAUDE_CONFIG_DIR/plans/p.md\"}")"
check "/lead session spawns general-purpose" deny lead-fanout-gate.py "$(pres "$SID" "" Agent "$(spawn general-purpose 'do x')")"
check "pr-worker inside a /lead session edits code" allow role-gate.py "$(pres "$SID" tech-lead:pr-worker Edit "$CODE")"
check "unmarked session edits repo code" allow role-gate.py "$(pres "other-sid" "" Edit "$CODE")"
check "agent self-approves PR text" deny pr-prose-gate.py "$(pre "" Bash '{"command":"prose-check.py --approve --body-file b.md"}')"
check "reading the prose gate log is not a prose mark" allow pr-prose-gate.py "$(pre "" Bash '{"command":"tail ~/.claude/tech-lead/state/prose-gate.log"}')"

printf '%s' '{"hook_event_name":"UserPromptSubmit","agent_type":"tech-lead:tech-lead","prompt":"Just start one PR until I have reviewed the base.","cwd":"/tmp"}' | python3 "$H/lead-session.py"
printf '%s' '{"hook_event_name":"UserPromptSubmit","agent_type":"tech-lead","prompt":"<teammate-message teammate_id=\"x\">done</teammate-message>","cwd":"/tmp"}' | python3 "$H/lead-session.py"
if grep -q "Just start one PR" "$LD/directives.md" && ! grep -q teammate "$LD/directives.md"; then PASS=$((PASS+1)); echo "ok   ledger records human prompts only"; else FAILN=$((FAILN+1)); echo "FAIL ledger"; fi
INJ=$(printf '%s' '{"hook_event_name":"SessionStart","source":"compact","agent_type":"tech-lead","transcript_path":"/tmp/x.jsonl","cwd":"/tmp"}' | python3 "$H/lead-session.py")
if grep -q "Just start one PR" <<<"$INJ" && grep -q -- "- red: " <<<"$INJ" && grep -q "Pat's directives" <<<"$INJ"; then PASS=$((PASS+1)); echo "ok   compaction re-injects directives and units"; else FAILN=$((FAILN+1)); echo "FAIL injection: ${INJ:0:300}"; fi
if grep -q '"owner_name": "Pat"' "$CLAUDE_CONFIG_DIR/tech-lead/config.json" 2>/dev/null; then PASS=$((PASS+1)); echo "ok   session start copies settings for scripts"; else FAILN=$((FAILN+1)); echo "FAIL settings copy"; fi

echo "---- $PASS passed, $FAILN failed"; exit $FAILN
