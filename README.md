# tech-lead

A Claude Code plugin that runs a tech-lead session. The lead splits a project into units and hands each unit to a `pr-worker` agent. Each worker delivers one draft PR and keeps it moving until CI and review are green. You review the PRs. The lead makes sure every PR that reaches you is ready, and that no open PR sits broken without an owner.

Hooks enforce the rules, so they hold after the conversation is compacted and when an agent would rather skip them.

- **Directives survive compaction.** Every message you type in a lead session goes into a ledger file, and the lead gets it back after every compaction.
- **No orphaned PRs.** A tracker watcher checks GitHub every minute while the board is changing, every five minutes when it is quiet, and backs off while GitHub rate-limits the account. A worker can't stop while its PR is red. The lead can't start new work while a red PR has no running owner, and a PR that stays red escalates.
- **Local checks before a push.** Workers push only through `ready-push.sh`, which runs the repo's static checks and refuses an unrecorded stacked base.
- **PR text passes a judge.** A Sonnet judge checks each PR title and body against your writing standard before `gh pr create`.
- **The lead coordinates and never codes.** It can't push, open PRs, edit code or reply to review threads.

## Install

```
/plugin marketplace add clintonb/tech-lead
/plugin install tech-lead@tech-lead
```

Claude Code asks for the settings when you install. Change them later with `/plugin configure tech-lead@tech-lead` or in `/config`. Then run `/tech-lead:setup` to write your personal files.

You need `git`, `gh` (signed in), `node` 20 or later and `python3`.

## Use

Start a lead in any session with `/tech-lead:lead <project>`, or start a fresh session as the lead:

```
claude --agent tech-lead:tech-lead
```

`bin/lead.sh <project> [--ask]` does the same from a terminal and names the project. It starts in bypass permissions mode, where deny rules and hooks still apply. `--ask` starts with permission prompts instead. Lead state lives in `~/.claude/leads/<project>/`: the directives ledger, `state.json` with the unit list, the inbox and the generated tracker page.

`/tech-lead:lead off` turns a session back into an ordinary one.

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| `owner_name` | (required) | How agents refer to you. |
| `review_bot` | blank | GitHub login prefix of a review bot whose review on the head commit gates readiness. The tracker reads `**P0**` to `**P3**` findings and an `APPROVE` first line from its review body. |
| `review_request` | blank | The PR comment that asks the bot for a review. |
| `tracker_publisher` | `none` | `none` keeps the tracker as `tracker/index.html` in the lead directory. `superset` publishes it with the `superset` CLI. |
| `push_gate` | `lead` | Where a push needs `check-head.sh` to pass first: `all` sessions, `lead` and worker sessions only, or `off`. |
| `prose_gate` | `lead` | Where PR text needs the judge to pass first: `all`, `lead` or `off`. |
| `repos_dir` | `~/workspace` | Where your checkouts live, as `<repos_dir>/<repo name>`. The watcher rebases conflicting PRs there. |
| `memory_dir` | blank | Where leads save lasting corrections as memory files. |
| `lab_cli` | blank | A remote lab CLI, such as `coder`. Agents may use it for lab runs only. |

## Personal files

`/tech-lead:setup` writes these to `~/.claude/tech-lead/`. Each one is optional.

| File | What it does |
| --- | --- |
| `pr-writing.md` | Your PR writing standard. Replaces [`rules/pr-writing.md`](rules/pr-writing.md). |
| `checks.json` | Which CI checks are static checks, tests or ignored, per repo. |
| `lead-rules.md` | Extra rules for the lead. |
| `worker-rules.md` | Extra rules for workers. |

## Static checks

`check-head.sh` runs the checks a repo declares, in this order:

1. A `check` script in `package.json`, run with `pnpm check`.
2. An executable `scripts/check` or `scripts/lint`, after `scripts/bootstrap` when it exists. In a Go repo it uses the Go version that `go.mod` pins.

A repo with none of these is skipped by the push gate. Add a `check` script to the repo rather than special-casing it.

## Tests

```
TEST_REPO=owner/name TEST_MERGED_PR=<n> tests/run.sh
```

The tests feed recorded tool calls to the hooks. The orphan and stop tests read live PR state, so they need an open red PR and a merged PR of yours in `TEST_REPO`. The run uses a temporary `CLAUDE_CONFIG_DIR`, so it never touches your real leads or settings.

## License

MIT
