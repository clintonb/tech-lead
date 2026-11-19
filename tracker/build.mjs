#!/usr/bin/env node
// Usage: node build.mjs <lead-dir> [--json] [--publish] [--watch]
//   --watch    every minute: rebase conflicting PRs, republish, and write new blockers to inbox/<owner>.log
//   --json     print {awaiting, inProgress, orphans} for the lead instead of rendering
//   --publish  publish when the content changed and the tracker_publisher setting names a publisher. For superset: a new
//              version of state.pageId, or a new org page whose id is saved there
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, statSync, writeFileSync } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { classify, fetchPrs, isRateLimited, labelOfKey, prKey, prLabel, unitRepo } from './pr-state.mjs';
import { liveOwners } from './owners.mjs';
import { rebaseConflicting } from './rebase.mjs';
import { option, ownerName } from './config.mjs';

// Every watcher shares one GitHub GraphQL budget, so a board that isn't changing polls less often.
const FAST_MS = 60 * 1000;
const SLOW_MS = 5 * 60 * 1000;
const QUIET_TICKS = 5;
const WAKE_CHECK_MS = 15 * 1000;
// A conflict needs only a rebase; other blockers can need real work before the next push.
const STALE_CONFLICT_MS = 10 * 60 * 1000;
const STALE_MS = 30 * 60 * 1000;

const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const pt = (iso) => (iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }) : '');
const readJson = (p, fallback) => (existsSync(p) ? JSON.parse(readFileSync(p, 'utf8')) : fallback);

function discover(state, repo) {
  if (!state.branchPrefixes?.length) { return []; }
  const out = execFileSync('gh', ['pr', 'list', '--repo', repo, '--state', 'open', '--author', '@me', '--limit', '200', '--json', 'number,headRefName'], { encoding: 'utf8' });
  return JSON.parse(out).filter((p) => state.branchPrefixes.some((b) => p.headRefName.startsWith(b))).map((p) => p.number);
}

// GitHub stacks that contain at least one of the given PRs, bottom first.
function fetchStacks(repo, numbers) {
  let stacks = [];
  try {
    const out = execFileSync('gh', ['api', '--paginate', `repos/${repo}/stacks?state=open&per_page=100`], { encoding: 'utf8' });
    stacks = JSON.parse(`[${out.trim().replace(/\]\s*\[/g, '],[')}]`).flat();
  } catch { return []; }
  return stacks
    .filter((st) => st.pull_requests.some((p) => numbers.has(p.number)))
    .map((st) => ({ repo, number: st.number, url: `https://github.com/${repo}/stack/${st.number}`, base: st.base.ref, prs: st.pull_requests.map((p) => ({ number: p.number, title: p.title, state: p.merged_at ? 'merged' : p.state })) }));
}

export function collect(dir) {
  const state = readJson(join(dir, 'state.json'), null);
  if (!state) { throw new Error(`${dir}/state.json is missing`); }

  const repos = [...new Set([state.repo, ...state.units.map((u) => unitRepo(state, u))])];
  const fetched = repos.flatMap((repo) => {
    const units = state.units.filter((u) => unitRepo(state, u) === repo);
    const refs = [...new Set([...units.map((u) => u.pr ?? u.branch).filter(Boolean).map(String), ...discover(state, repo).map(String)])];
    return refs.length ? fetchPrs(refs, repo) : [];
  });
  const live = liveOwners(dir);
  const rebaseLog = readJson(join(dir, 'rebase-log.json'), {});
  const prs = [];
  for (const pr of fetched) {
    if (!pr || pr.state !== 'OPEN') { continue; }
    const c = classify(pr);
    c.key = prKey(state, c.repo, c.number);
    c.label = prLabel(state, c.repo, c.number);
    const unit = state.units.find((u) => unitRepo(state, u) === c.repo && (String(u.pr) === String(c.number) || u.branch === c.branch));
    c.unit = unit?.id ?? null;
    c.owner = unit?.owner ?? null;
    c.paused = unit?.status === 'paused';
    c.ownerLive = Boolean(c.owner && live.has(c.owner));
    const rb = rebaseLog[c.key];
    const conflict = `conflicts with ${c.base}`;
    if (rb?.result === 'conflict' && rb.head === c.head && rb.files.length) {
      c.actions = c.actions.map((a) => (a === conflict ? `${conflict}, auto-rebase failed in ${rb.files.join(', ')}` : a));
    } else if (rb?.result === 'no-checkout' && rb.head === c.head) {
      c.actions = c.actions.map((a) => (a === conflict ? `${conflict}, no local checkout of ${c.repo} to auto-rebase: rebase it by hand` : a));
    }
    if (unit?.labBlocksReview && !unit.lab && (c.state === 'yellow' || c.state === 'green')) {
      c.state = 'waiting';
      c.waits.push(`lab run ${ownerName()} made a blocker is not recorded`);
    }
    prs.push(c);
  }

  const openKeys = new Set(prs.map((p) => p.key));
  const stacks = repos.flatMap((repo) => fetchStacks(repo, new Set(prs.filter((p) => p.repo === repo).map((p) => p.number))));
  const byKey = new Map(prs.map((p) => [p.key, p]));
  for (const st of stacks) {
    st.prs.forEach((sp) => { sp.key = prKey(state, st.repo, sp.number); sp.label = prLabel(state, st.repo, sp.number); });
    st.prs.forEach((sp, i) => {
      const p = byKey.get(sp.key);
      if (!p) { return; }
      const below = st.prs.slice(0, i).filter((b) => b.state !== 'merged');
      p.stack = { number: st.number, url: st.url, position: i + 1, size: st.prs.length, mergesAfter: below.map((b) => b.number), mergesAfterLabels: below.map((b) => b.label) };
    });
    st.prs.forEach((sp) => { const p = byKey.get(sp.key); sp.trackerState = p?.state ?? sp.state; sp.title = sp.title || p?.title || ''; });
  }
  return {
    state,
    stacks,
    autoMerging: prs.filter((p) => p.autoMerge && p.state !== 'red'),
    awaiting: prs.filter((p) => !p.autoMerge && (p.state === 'yellow' || p.state === 'green')),
    inProgress: prs.filter((p) => p.state === 'red' || (!p.autoMerge && p.state === 'waiting')),
    orphans: prs.filter((p) => p.state === 'red' && !p.ownerLive && !p.paused),
    notStarted: state.units.filter((u) => !u.pr && !prs.some((p) => p.repo === unitRepo(state, u) && p.branch === u.branch) && u.status !== 'merged' && u.status !== 'dropped'),
    merged: state.units.filter((u) => u.status === 'merged' || (u.pr && !openKeys.has(prKey(state, unitRepo(state, u), u.pr)) && u.status !== 'dropped')),
  };
}

const stackNote = (p) => (p.stack
  ? `<br><small><a href="${esc(p.stack.url)}">stack #${p.stack.number}</a>, ${p.stack.position} of ${p.stack.size}${p.stack.mergesAfter.length ? `, merges after ${p.stack.mergesAfterLabels.join(', ')}` : ', merges first'}</small>`
  : !['master', 'main'].includes(p.base) ? `<br><small class="warn">based on ${esc(p.base)}, not in a GitHub stack</small>` : '');
const prCell = (p) => `<a href="${esc(p.url)}">${esc(p.label)}</a> ${esc(p.title)}${stackNote(p)}`;
const size = (p) => `+${p.additions.toLocaleString('en-US')}/&minus;${p.deletions.toLocaleString('en-US')}`;

const ANSWERED_DAYS = 3;

function renderQuestions(questions) {
  const waiting = questions.filter((q) => q.status === 'open' || q.status === 'pending');
  const cutoff = Date.now() - ANSWERED_DAYS * 86400e3;
  const answered = questions.filter((q) => q.status === 'answered' && Date.parse(q.answeredAt) >= cutoff).reverse();
  if (!waiting.length && !answered.length) { return ''; }
  const waitRows = waiting.map((q) => `<tr class="${q.status === 'open' ? 'orphan' : ''}"><td>${pt(q.asked)}</td><td>${esc(q.text)}</td><td>${q.status === 'open' ? '<strong>No answer yet</strong>' : `Finding out: ${esc(q.pending)}`}</td></tr>`);
  const ansRows = answered.map((q) => `<tr><td>${pt(q.asked)}</td><td>${esc(q.text)}</td><td>${esc(q.answer)}<br><small>${pt(q.answeredAt)}</small></td></tr>`);
  return `<h2>Your questions (${waiting.length} waiting)</h2>
${waitRows.length ? `<div class="wide"><table><tr><th>Asked</th><th>Question</th><th>Status</th></tr>${waitRows.join('')}</table></div>` : '<p class="lede">Every question has an answer.</p>'}
${ansRows.length ? `<details open><summary>Answered in the last ${ANSWERED_DAYS} days (${ansRows.length})</summary><div class="wide"><table><tr><th>Asked</th><th>Question</th><th>Answer</th></tr>${ansRows.join('')}</table></div></details>` : ''}`;
}

function render(view, questions = []) {
  const { state, awaiting, autoMerging, inProgress, notStarted, stacks } = view;
  const STATE_LABEL = { red: 'blocked', waiting: 'checks running', yellow: 'tests running', green: 'green', merged: 'merged', open: 'open', closed: 'closed' };
  const stackItems = stacks.map((st) => `<li><a href="${esc(st.url)}">Stack #${st.number}</a> onto ${esc(st.base)}, merge bottom first: ${st.prs.map((sp) => `<a href="https://github.com/${esc(st.repo)}/pull/${sp.number}">${esc(sp.label)}</a> ${esc(sp.title)} <small>(${esc(STATE_LABEL[sp.trackerState] ?? sp.trackerState)})</small>`).join(' &rarr; ')}</li>`);
  const lab = (p) => esc(state.units.find((u) => u.id === p.unit)?.lab ?? 'not run');
  const awaitRows = awaiting.map((p) => `<tr><td>${prCell(p)}</td><td>${p.state === 'green' ? 'All checks green' : `Tests running (${p.testsRunning.length})`}</td><td class="num">${size(p)}</td><td>${lab(p)}</td><td>${p.minorFindings?.length ? esc(p.minorFindings.join('; ')) : ''}</td><td>${pt(p.pushedAt)}</td></tr>`);
  const progRows = inProgress
    .map((p) => `<tr class="${p.state === 'red' && !p.ownerLive ? 'orphan' : ''}"><td>${prCell(p)}</td><td>${esc(p.owner ?? 'no owner')}${p.owner && !p.ownerLive ? ' <strong>(not running)</strong>' : ''}</td><td>${p.paused ? '<strong>Paused.</strong> ' : ''}${p.autoMerge ? '<strong>Auto-merge on.</strong> ' : ''}${esc([...p.actions, ...p.waits].join('; '))}</td><td class="num">${size(p)}</td></tr>`);
  const autoRows = autoMerging.map((p) => `<tr><td>${prCell(p)}</td><td>${p.state === 'green' ? 'All checks green' : p.state === 'yellow' ? `Tests running (${p.testsRunning.length})` : esc(p.waits.join('; '))}</td><td>${esc(p.autoMerge.method.toLowerCase())}${p.autoMerge.by ? ` by ${esc(p.autoMerge.by)}` : ''}<br><small>${pt(p.autoMerge.enabledAt)}</small></td><td class="num">${size(p)}</td></tr>`);
  const todo = notStarted.map((u) => `<li>${esc(u.title ?? u.id)}${u.owner ? ` (${esc(u.owner)})` : ''}</li>`);
  return `
<h1>${esc(state.title)}</h1>
${renderQuestions(questions)}
<h2>Awaiting ${esc(ownerName())} (${awaiting.length})</h2>
${awaitRows.length ? `<div class="wide"><table><tr><th>PR</th><th>CI</th><th>Size</th><th>Lab</th><th>Declined P2/P3 on head</th><th>Last push</th></tr>${awaitRows.join('')}</table></div>` : '<p class="lede">Nothing is ready for review.</p>'}
<h2>Auto-merging (${autoMerging.length})</h2>
${autoRows.length ? `<div class="wide"><table><tr><th>PR</th><th>CI</th><th>Auto-merge</th><th>Size</th></tr>${autoRows.join('')}</table></div>` : '<p class="lede">None.</p>'}
<h2>In progress (${inProgress.length})</h2>
${progRows.length ? `<div class="wide"><table><tr><th>PR</th><th>Owner</th><th>Blockers</th><th>Size</th></tr>${progRows.join('')}</table></div>` : '<p class="lede">None.</p>'}
${stackItems.length ? `<h2>Stacks (${stackItems.length})</h2><ul>${stackItems.join('')}</ul>` : ''}
${todo.length ? `<h2>Not started (${todo.length})</h2><ul>${todo.join('')}</ul>` : ''}`;
}

const STYLE = `<style>
  main { max-width: 80rem; margin: 0 auto; padding: 2rem 1rem 4rem; }
  .wide { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
  th, td { text-align: left; padding: 0.35rem 0.6rem; border-bottom: 1px solid var(--sp-border, #ddd); vertical-align: top; }
  th { color: var(--sp-muted, #666); font-weight: 600; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  small, .lede { color: var(--sp-muted, #666); }
  .warn { color: #b4531f; }
  summary { cursor: pointer; color: var(--sp-muted, #666); margin: 0.5rem 0; }
  tr.orphan td { background: rgba(220, 60, 40, 0.08); }
</style>`;

// Appends one line per new blocker to <dir>/inbox/<owner>.log, or inbox/lead.log when the owner is not running.
// Owners and the lead tail their file with a background Monitor, so a line wakes them.
// Runs one tick, then sleeps FAST_MS while the board changes, SLOW_MS after QUIET_TICKS unchanged ticks, and until the
// GraphQL reset after a rate-limit error. An edit to state.json ends any sleep early.
function watch(dir) {
  let lastSig = null;
  let quiet = 0;
  let limited = 0;
  const log = (msg) => console.error(`${new Date().toISOString()} ${msg}`);
  const stateMtime = () => { try { return statSync(join(dir, 'state.json')).mtimeMs; } catch { return 0; } };
  const tick = () => {
    let delay = FAST_MS;
    try {
      const { view } = build(dir, { publish: true });
      notify(dir, view);
      const prs = [...view.inProgress, ...view.awaiting, ...view.autoMerging];
      try { rebaseConflicting(dir, { prs }); } catch (e) { log(`rebase failed: ${e.message.split('\n')[0]}`); }
      const sig = JSON.stringify(prs.map((p) => [p.key, p.state, p.head, p.actions, p.waits, p.ownerLive]).sort());
      quiet = sig === lastSig ? quiet + 1 : 0;
      lastSig = sig;
      delay = quiet >= QUIET_TICKS ? SLOW_MS : FAST_MS;
      limited = 0;
    } catch (e) {
      if (isRateLimited(e)) {
        limited++;
        delay = rateLimitWait(limited);
        log(`GitHub rate limit hit, sleeping ${Math.round(delay / 60000)} min`);
      } else {
        log(`build failed: ${e.message.split('\n')[0]}`);
      }
    }
    const due = Date.now() + delay;
    const since = stateMtime();
    const wait = () => {
      if (Date.now() >= due || stateMtime() !== since) { tick(); } else { setTimeout(wait, Math.min(WAKE_CHECK_MS, due - Date.now())); }
    };
    setTimeout(wait, Math.min(WAKE_CHECK_MS, delay));
  };
  tick();
}

// The REST rate_limit endpoint doesn't count against any budget. It reports only this token's GraphQL points, while
// GitHub can refuse on a budget shared by every token of the user. When this token still has points, the reset it
// reports says nothing about the shared one, so back off in steps instead.
function rateLimitWait(attempt) {
  const backoff = Math.min(SLOW_MS * 2 ** (attempt - 1), 30 * 60 * 1000);
  try {
    const { remaining, reset } = JSON.parse(execFileSync('gh', ['api', 'rate_limit', '--jq', '.resources.graphql'], { encoding: 'utf8' }));
    return remaining > 0 ? backoff : Math.min(Math.max(reset * 1000 - Date.now() + 30 * 1000, FAST_MS), 60 * 60 * 1000);
  } catch {
    return backoff;
  }
}

export function notify(dir, view) {
  const statePath = join(dir, 'notify-state.json');
  const prev = readJson(statePath, {});
  const next = {};
  const inbox = join(dir, 'inbox');
  mkdirSync(inbox, { recursive: true });
  const at = new Date().toISOString();
  const send = (who, line) => appendFileSync(join(inbox, `${who}.log`), `${at} ${line}\n`);
  for (const p of [...view.inProgress, ...view.awaiting, ...view.autoMerging]) {
    if (p.paused) { continue; }
    const sig = p.state === 'red' ? `${p.head} ${[...p.actions].sort().join(' | ')}` : p.state;
    next[p.key] = sig;
    if (p.state === 'red') {
      // One line per new blocker is not enough: a routed blocker can still sit unworked, so a red head that
      // hasn't moved escalates to the lead until it does.
      const limit = p.actions.some((a) => a.startsWith('conflicts with')) ? STALE_CONFLICT_MS : STALE_MS;
      const [head, since, warned] = (prev[`red:${p.key}`] ?? '').split(' ');
      const start = head === p.head ? Number(since) : Date.parse(at);
      const lastWarn = head === p.head ? Number(warned || 0) : 0;
      const now = Date.parse(at);
      let warnedAt = lastWarn;
      if (now - start >= limit && now - (lastWarn || start) >= limit) {
        const mins = Math.round((now - start) / 60000);
        send('lead', `STALE ${p.label} ${p.url} has been red for ${mins} min with no new push (owner ${p.owner ?? 'none'}): ${p.actions.join('; ')}. Messages are not reaching a fix. Spawn a dedicated pr-worker for this PR alone now, and stop the old owner from touching its branch.`);
        warnedAt = now;
      }
      next[`red:${p.key}`] = `${p.head} ${start} ${warnedAt}`;
    }
    if (prev[p.key] === sig) { continue; }
    if (p.state === 'red') {
      const line = `${p.label} ${p.url} is red: ${p.actions.join('; ')}`;
      if (p.owner && p.ownerLive) { send(p.owner, line); } else { send('lead', `ORPHAN ${line} (owner ${p.owner ?? 'none'} is not running)`); }
    } else if ((p.state === 'yellow' || p.state === 'green') && prev[p.key] !== undefined) {
      send('lead', `READY ${p.label} ${p.url} is ${p.state}`);
    }
  }
  const redByOwner = {};
  for (const p of view.inProgress) {
    if (p.state === 'red' && p.owner && !p.paused) { (redByOwner[p.owner] ??= []).push(p.key); }
  }
  for (const [owner, keys] of Object.entries(redByOwner)) {
    const key = `overloaded:${owner}`;
    next[key] = keys.sort().join(',');
    if (keys.length > 1 && prev[key] !== next[key]) {
      send('lead', `OVERLOADED ${owner} owns ${keys.length} red PRs (${keys.map(labelOfKey).join(', ')}) and works them one at a time. Spawn a separate pr-worker for each extra PR now.`);
    }
  }
  const { state } = view;
  for (const key of Object.keys(prev)) {
    if (key.startsWith('overloaded:') || key.startsWith('red:') || next[key] !== undefined) { continue; }
    const unit = state.units.find((u) => u.pr && prKey(state, unitRepo(state, u), u.pr) === key);
    if (unit?.status === 'paused') { continue; }
    const line = `CLOSED ${labelOfKey(key)} is merged or closed. Stop all work on it, and never report it as ready.`;
    send('lead', line);
    if (unit?.owner) {
      send(unit.owner, line);
      const stillOwns = view.state.units.some((u) => u.owner === unit.owner && u !== unit && !['merged', 'dropped', 'paused'].includes(u.status));
      if (!stillOwns) { send('lead', `SHUTDOWN ${unit.owner} has no open PRs left. Send it a shutdown_request.`); }
    }
  }
  writeFileSync(statePath, JSON.stringify(next));
}

// The lead edits state.json too, so re-read it right before adding the new page's id.
function recordPage(dir, res) {
  const page = res.page ?? res;
  const id = page.id ?? page.pageId;
  if (!id) { throw new Error(`superset pages publish returned no page id: ${JSON.stringify(res).slice(0, 200)}`); }
  const path = join(dir, 'state.json');
  const state = JSON.parse(readFileSync(path, 'utf8'));
  state.pageId = id;
  state.pageUrl = page.url ?? res.url ?? state.pageUrl;
  writeFileSync(`${path}.tmp`, JSON.stringify(state, null, 2));
  renameSync(`${path}.tmp`, path);
}

function build(dir, { publish }) {
  const view = collect(dir);
  const body = render(view, readJson(join(dir, 'questions.json'), []));
  const hash = createHash('sha256').update(body).digest('hex');
  const outDir = join(dir, 'tracker');
  mkdirSync(outDir, { recursive: true });
  const statePath = join(outDir, 'published.json');
  const prev = readJson(statePath, {});
  const out = join(outDir, 'index.html');
  writeFileSync(out, `<!doctype html><html lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>${esc(view.state.title)}</title>${STYLE}</head><body class="auto"><main><p class="lede"><small>Built ${pt(new Date().toISOString())} from live GitHub state.</small></p>${body}</main></body></html>`);
  if (publish && option('tracker_publisher') === 'superset' && prev.hash !== hash) {
    const label = `${view.awaiting.length} awaiting, ${view.inProgress.length} in progress`;
    const target = view.state.pageId ? ['--page', view.state.pageId] : ['--visibility', 'org', '--no-watch'];
    const res = JSON.parse(execFileSync('superset', ['pages', 'publish', out, ...target, '--label', label, '--title', view.state.title ?? basename(dir), '--json'], { encoding: 'utf8' }));
    if (!view.state.pageId) { recordPage(dir, res); }
    writeFileSync(statePath, JSON.stringify({ hash }));
  }
  return { view, out };
}

const args = process.argv.slice(2);
const dir = resolve(args.find((a) => !a.startsWith('--')) ?? '.');
if (import.meta.url !== `file://${process.argv[1]}`) {
  // Imported as a module: run nothing.
} else if (args.includes('--json')) {
  const v = collect(dir);
  const brief = (p) => ({ repo: p.repo, number: p.number, label: p.label, url: p.url, state: p.state, draft: p.draft, paused: p.paused, autoMerge: Boolean(p.autoMerge), owner: p.owner, ownerLive: p.ownerLive, actions: p.actions, waits: p.waits, stack: p.stack ?? null });
  console.log(JSON.stringify({ awaiting: v.awaiting.map(brief), autoMerging: v.autoMerging.map(brief), inProgress: v.inProgress.map(brief), orphans: v.orphans.map(brief), stacks: v.stacks, notStarted: v.notStarted.map((u) => u.id), questions: readJson(join(dir, 'questions.json'), []).filter((q) => q.status === 'open' || q.status === 'pending') }, null, 2));
} else if (args.includes('--watch')) {
  watch(dir);
} else {
  console.log(build(dir, { publish: args.includes('--publish') }).out);
}
