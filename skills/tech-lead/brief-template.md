UNIT: <unit id from state.json>
LEAD_DIR: <absolute lead directory>

You are a tech-lead:pr-worker. Your rules are in worker-rules.md, as your agent prompt says.

**Goal:** <one sentence in the owner's terms: what is true after this PR merges>

**Behavior:**
- <at most five bullets, each a behavior a reader can check against real data>

**Not in scope:** <what a reader might expect here but belongs elsewhere>

**Where:** branch `<branch>` from the default branch, or from `<stackOn>` when state.json records a stack for this unit, in <local worktree path>.

**Lab:** <only when the owner asked for one: data, what the baseline diff must show, and whether it blocks review | "none">

**PR:** title `<literal title>`. Body:
<literal body, then Closes/Relates lines>
