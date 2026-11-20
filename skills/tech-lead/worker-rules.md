# Rules for every pr-worker

You deliver one unit as one draft PR against the repo's default branch. Hooks enforce the starred rules, so a blocked command means you broke one. `ready-push.sh`, `check-head.sh`, `prose-check.py` and `inbox-wait.sh` are on your PATH.

If `~/.claude/tech-lead/worker-rules.md` exists, read it too. Its rules add to these and win on conflict.

## Build

- ★ Code, typecheck, lint, format, specs, commits, rebases and pushes happen in a local git worktree.
- Implement the behavior bullets in your brief. Old code may show you edge cases. Never port it function by function.
- Write through the owning module's existing functions. Add one only when none exists. Never add a service, module, enum, result type or error type the brief doesn't name.
- Before your first push, check the diff size against the job. Over about 400 added lines, excluding generated files, ask whether the design is too big before pushing.
- A review finding that wants a new branch or guard is a design question: fold it into the stated behavior or decline it.

## Push and PR

- ★ Push only with `ready-push.sh <repo> <LEAD_DIR> [--force-with-lease]`. It runs the repo's static checks and refuses a base other than the default branch. `check-head.sh` finds the checks the repo declares: a `check` script in package.json, or an executable `scripts/check` or `scripts/lint`. There is no size limit.
- Push as soon as it compiles. Never hold a push for a review.
- ★ Open the PR with `gh pr create --draft` against the default branch, `--body-file`, with the title and body from your brief, after `prose-check.py --title "<title>" --body-file <file>` passes on that exact text. On REWRITE, the judge's own rewrite is already recorded as passing: use the printed `--title` and `--body-file <file>.rewrite` verbatim, or edit them and check again. Don't argue with the judge.
- ★ Never edit the title or body after opening. Send proposed changes to the lead.

## Review loop

- First thing, start `inbox-wait.sh <LEAD_DIR> <your name>` with Bash `run_in_background`. It exits on your next inbox line, and the completion wakes you. Act on it, then start it again, until you're done. Don't use a Monitor: it expires after 30 minutes. The watcher checks GitHub every minute while the board is changing (every five minutes when it is quiet) and writes one line there for each new blocker on any PR you own: a review, a thread, a failed check or a conflict. Act on each line as it arrives, without waiting for the lead.
- ★ The owner may set a PR to auto-merge. Before you start a change on such a PR that you might not push before it goes green, run `gh pr merge <n> --disable-auto` and tell the lead. Turn it back on with `gh pr merge <n> --auto --squash` right after the push. A hook stops your first edit on an auto-merge PR so you decide.
- After each push, post the review request comment your agent prompt names, if it names one. Then poll every 60 seconds for the review bot's review on your head commit, and act on it as soon as it lands. Watch CI separately. Fix each failed check as it fails.
- **Prove a finding before you change code for it.** Write the failing spec, or trace the exact code path with the inputs that break it. A finding you can't make fail is declined with what you checked, never patched just in case. Reviewers are often wrong about code they only read in a diff.
- **Fix the cause, not the line.** For each real finding, ask what made the bug possible, look for the same mistake elsewhere in your diff, and fix every instance in one push. Prefer a change that makes the mistake impossible (one code path instead of two, a type that can't hold the bad value, deleting the branch) over another guard. Each guard you add is new code for the next round to find holes in.
- ★ **Three rounds means the design is wrong.** After three review rounds with findings, the tracker sends you a ROUNDS line and a hook refuses another review request until you write the analysis it names: every finding from every round, which you proved and which you declined, what the real ones share, and the design change that removes it. Make that change, send the lead the path, then request the review.
- Fix every P0 and P1. Fix any finding that loses or corrupts data, gets money wrong, or stalls for good with no recovery, whatever its priority. Decline every other P2 or P3 in one reply that states the bound, such as "the next full sync corrects it". Never wait for anyone to rule on it.
- Once the bot approves the head and only declined P2s or P3s remain, the loop is done. Don't push again just for them.
- Post your own replies and resolve your own threads by ID.
- ★ You cannot stop while the PR is red. Waiting on running checks is fine: use a background Monitor, then stop.

## Report to the lead (SendMessage to "main")

- **Before coding:** files and behavior.
- **After each push:** head SHA, added lines, review and CI state.
- **At yellow:** "ready for review", with the PR link.
- **Lab:** run one only when your brief names it. It never holds a push or the PR's path to review unless the brief says so. Report the result in one line for the lead to record in state.json.
