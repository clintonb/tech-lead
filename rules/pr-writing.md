# PR writing standard

The default standard the prose judge applies. Run `/tech-lead:setup` to write your own copy to `~/.claude/tech-lead/pr-writing.md`, which replaces this file.

## Title

- Names the outcome, not the mechanism. No ticket ID, no `feat:`-style prefix.
- Tense follows what the PR does. Past tense when it changed existing behavior ("Fixed duplicate invoice emails"). Present tense when it adds a capability ("Export orders as CSV"). "Added <thing>" when the thing itself is what was added ("Added a Postgres dashboard").

## Body

- Describes the behavior after the change, in present tense and plain prose, at the level a product reader cares about. A feature or change PR never describes the old behavior: no "Before", "used to" or "Now".
- **A bug-fix, infra or performance PR states the problem, then the fix.** Up to two sentences say what went wrong and, in plain words, why. Then one sentence says what the change does, at the level an engineer would say it out loud. Both parts are required. Code-level cause means class, method, column or config-key names, stack traces, logs and query output, and those stay out, as does the investigation. A body that omits the problem or what the fix does is a REWRITE (hard).
- **A performance PR states the time it saves.** The headline before and after time is the outcome, e.g., "A nightly sync finishes in 4 minutes instead of 40." Never strike it as a timing or a number. A benchmark table or a list of runs stays out.
- Keep a `Closes` or `Relates to` line when the author has one, as written. Never REWRITE for a missing ticket line, and never invent one.
- (hard) Contains none of these: headers, bullet-point changelogs, code blocks, tables, test plans or verification steps, restated CI results, evidence or investigation narrative, row counts, timings from an investigation or test run, class, method, column or config names, deploy steps, follow-up or interim caveats, PR dependency notes, AI attribution.
- (hard) No hard-wrapped lines and no smart quotes.
- **Short.** One short paragraph per behavior, main behavior first. Most PRs need under 60 words before the ticket line. Over 100 words is a REWRITE (hard).
- **The rule, not the cases.** Name a category once, with "e.g." and one or two members if needed. Never enumerate every type, path or edge case the code handles.
- (hard) **No sample data.** No record names, IDs, customer names, thresholds or ratios, unless the number is the behavior itself.
- **Actor and verb first.** Every sentence opens with who or what acts, then the verb: "The import creates...". Never open with a qualifier such as "When...", "For each..." or "If...".
- **Active voice.** Passive is fine only when the actor doesn't matter.
- **No filler.** No "This PR", "ensures", "comprehensive" or "robust", no hedges, no restating the title, no parenthetical asides.

## Bodies that pass

```
Fixed duplicate invoice emails

The billing worker retried a send after a timeout even when the first send had gone through, so some customers got the same invoice twice. The worker now records each send before retrying and skips invoices it already sent.
```

```
Export orders as CSV

A store manager can download the orders in the current filter as a CSV file from the orders page.

Closes ABC-123
```
