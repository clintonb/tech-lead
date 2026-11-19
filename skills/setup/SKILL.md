---
name: setup
description: Configure the tech-lead plugin for this user. Writes their PR writing standard, CI check classes per repo, and extra lead and worker rules under ~/.claude/tech-lead/, and points them at the plugin settings. Use for /tech-lead:setup, "configure tech-lead", changing the PR rules the judge applies, or adding a repo to the tracker.
disable-model-invocation: true
---

# Set up tech-lead

The plugin has two kinds of preference.

- **Settings** are short values in the plugin's `userConfig`: name, review bot, tracker publisher, gates, repos directory, memory directory, lab CLI. Claude Code stores them. Change them with `/plugin configure tech-lead@tech-lead` or `/config`.
- **Personal files** are longer text the plugin reads from `~/.claude/tech-lead/`. This skill writes them. Each one replaces or adds to a plugin default, and none is required.

| File | What it does |
| --- | --- |
| `pr-writing.md` | The PR writing standard the prose judge applies. Replaces `${CLAUDE_PLUGIN_ROOT}/rules/pr-writing.md`. |
| `checks.json` | Which CI checks are static checks, tests or ignored, per repo. Replaces the plugin's empty default. |
| `lead-rules.md` | Extra rules for the tech lead. Added to the `tech-lead` skill and wins on conflict. |
| `worker-rules.md` | Extra rules for pr-workers. Added to the shared worker rules and wins on conflict. |

Re-running this skill updates the files. Write each file whole, so a re-run gives the same result.

## Steps

### 1. Show the settings

Read `~/.claude/tech-lead/config.json`, which a hook copies from the plugin settings at session start. Show each value. If the file is missing or a value looks wrong, tell the user to run `/plugin configure tech-lead@tech-lead`, then start a new session so the copy refreshes. Don't edit `config.json` yourself: the next session overwrites it.

### 2. PR writing standard

Read `~/.claude/tech-lead/pr-writing.md` if it exists, otherwise the plugin default. Ask the user, with `AskUserQuestion`, whether to:

- keep the plugin default (write nothing, or delete their copy if they ask),
- import rules they already keep elsewhere, such as a "PR titles and descriptions" section in `~/.claude/CLAUDE.md`, or
- change specific rules: title tense, the problem-then-fix shape for bug fixes, the word limit, ticket lines, what never goes in a body.

Write the result to `~/.claude/tech-lead/pr-writing.md`. Keep the (hard) markers on the rules that must force a REWRITE, because the judge passes everything else. Include two or three example bodies that pass, in the user's own domain. Then offer to check a sample PR with `prose-check.py --title "<title>" --body-file <file>` to confirm the judge reads it.

### 3. CI check classes

Ask which repos the leads will work in. For each one, list its CI job and status-check names from `.github/workflows/` in the local checkout under the `repos_dir` setting, or from `gh pr checks` on a recent PR. Sort each name into:

- `test`: slow test jobs. A PR with only these still running is yellow, ready to review.
- `ignore`: checks that never matter for readiness, such as policy bots that stay pending on drafts.
- anything else counts as a static check, which must pass before the PR is ready.

Confirm the sorting with the user, then write `~/.claude/tech-lead/checks.json` with a `default` entry and one `"owner/name"` entry per repo that differs. Patterns are case-insensitive regular expressions. Set `"reviewBot": false` on a repo where the review bot doesn't run. Merge with any existing file rather than dropping repos the user didn't mention.

```json
{
  "default": { "ignore": ["^policy-bot"], "test": ["^unit-tests", "^e2e"] },
  "acme/docs": { "ignore": [], "test": ["^build$"], "reviewBot": false }
}
```

### 4. Extra rules

Ask whether leads or workers need rules the plugin doesn't carry. Typical ones:

- tools they must use for something, such as a read-only cluster wrapper,
- where lab runs happen and what data they use,
- quality steps, such as a cleanup skill to run past a diff size,
- how memories are mirrored to a team store.

Write lead rules to `~/.claude/tech-lead/lead-rules.md` and worker rules to `~/.claude/tech-lead/worker-rules.md` as short bullets. Skip a file when there's nothing for it.

### 5. Push gate repos

`check-head.sh` runs the static checks a repo declares: a `check` script in package.json, or an executable `scripts/check` or `scripts/lint`. For each repo from step 3, check that one of these exists. If none does, tell the user the push gate skips that repo, and that the fix is a `check` script in the repo itself.

### 6. Confirm

List each file written or left alone, and the settings that need `/plugin configure`. Remind the user that the gates and agents pick up the personal files on their next read, and the settings in the next session.
