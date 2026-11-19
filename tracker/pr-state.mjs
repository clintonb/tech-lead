#!/usr/bin/env node
// Classifies open PRs as red (action needed), waiting, yellow (ready for the owner's review) or green.
// Usage: node pr-state.mjs [--repo owner/name] <pr-number|branch>...   (prints one JSON object per line)
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { checksFor, option } from './config.mjs';

export { checksFor };
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
// The review bot whose review on the head gates readiness, and the comment that asks it for one. Blank: no bot.
const BOT = option('review_bot').trim();
const REQUEST = option('review_request').trim();
const REQUEST_RE = new RegExp(escapeRe(REQUEST).replace(/\s+/g, '\\s+'), 'i');
export const repoOfUrl = (url) => new URL(url).pathname.split('/').slice(1, 3).join('/');

// A PR is identified by (repo, number). A unit's own `repo` overrides state.repo. PRs in state.repo keep the bare
// number as key and `#n` as label, so notify-state.json, rebase-log.json and inbox lines read as before; PRs in any
// other repo use `owner/name#n` as key and `name#n` as label.
export const unitRepo = (state, unit) => unit?.repo ?? state.repo;
export const prKey = (state, repo, number) => (repo === state.repo ? String(number) : `${repo}#${number}`);
export const prLabel = (state, repo, number) => (repo === state.repo ? `#${number}` : `${repo.split('/')[1]}#${number}`);
export const labelOfKey = (key) => (/^\d+$/.test(key) ? `#${key}` : key.split('/')[1]);
const matches = (patterns, name) => patterns.some((p) => new RegExp(p, 'i').test(name));

const retry = (fn) => {
  let err;
  for (let i = 0; i < 3; i++) {
    try { return fn(); } catch (e) { err = e; execFileSync('sleep', ['2']); }
  }
  throw err;
};
const gql = (query) => retry(() => JSON.parse(execFileSync('gh', ['api', 'graphql', '-f', `query=${query}`], { encoding: 'utf8', maxBuffer: 64 << 20 })));

const PR_FIELDS = `number title url state isDraft additions deletions baseRefName headRefName mergeable headRefOid
  author { login }
  autoMergeRequest { enabledAt mergeMethod enabledBy { login } }
  reviewThreads(first: 100) { nodes { id isResolved comments(first: 1) { nodes { author { login } path } } } }
  reviews(last: 50) { nodes { author { login } submittedAt body commit { oid } } }
  comments(last: 30) { nodes { body createdAt } }
  commits(last: 1) { nodes { commit { committedDate statusCheckRollup { contexts(first: 100) { nodes { __typename
    ... on CheckRun { name conclusion status startedAt completedAt } ... on StatusContext { context state createdAt } } } } } } }`;

export function fetchPrs(refs, repo) {
  const [owner, name] = repo.split('/');
  const field = (r, i) => /^\d+$/.test(String(r))
    ? `p${i}: pullRequest(number: ${r}) { ${PR_FIELDS} }`
    : `p${i}: pullRequests(headRefName: "${r}", states: OPEN, first: 1) { nodes { ${PR_FIELDS} } }`;
  const data = gql(`{ repository(owner: "${owner}", name: "${name}") { ${refs.map(field).join('\n')} } }`).data.repository;
  return refs.map((r, i) => {
    const v = data[`p${i}`];
    return v?.nodes ? v.nodes[0] ?? null : v;
  });
}

export function classify(pr) {
  const repo = repoOfUrl(pr.url);
  const config = checksFor(repo);
  const head = pr.commits.nodes[0]?.commit;
  const contexts = head?.statusCheckRollup?.contexts.nodes ?? [];
  const failed = { static: [], test: [] };
  const pending = { static: [], test: [] };
  let started = 0;
  for (const c of contexts) {
    const name = c.name ?? c.context;
    if (matches(config.ignore, name)) { continue; }
    started++;
    const kind = matches(config.test, name) ? 'test' : 'static';
    const done = c.__typename === 'CheckRun' ? c.status === 'COMPLETED' : !['PENDING', 'EXPECTED'].includes(c.state);
    const ok = c.__typename === 'CheckRun' ? ['SUCCESS', 'NEUTRAL', 'SKIPPED'].includes(c.conclusion) : c.state === 'SUCCESS';
    if (!done) { pending[kind].push(name); } else if (!ok) { failed[kind].push(name); }
  }

  const openThreads = pr.reviewThreads.nodes.filter((t) => !t.isResolved).map((t) => ({
    id: t.id, author: t.comments.nodes[0]?.author?.login, path: t.comments.nodes[0]?.path,
  }));
  const useBot = Boolean(BOT) && config.reviewBot !== false;
  const botReviews = useBot ? pr.reviews.nodes.filter((r) => (r.author?.login ?? '').startsWith(BOT) && r.body.trim()) : [];
  const onHead = botReviews.filter((r) => r.commit?.oid === pr.headRefOid).at(-1);
  // P0 and P1 items block even under an APPROVE header. P2 and P3 items are shown for the owner to judge: chasing them
  // never converges, and owners fix the data-affecting ones before reporting ready.
  const listed = onHead ? [...onHead.body.matchAll(/\*\*P(\d)\*\*\s+([^\n]+)/g)].map((m) => ({ p: Number(m[1]), title: m[2].trim() })) : [];
  const findings = listed.filter((f) => f.p <= 1).map((f) => f.title);
  const minorFindings = listed.filter((f) => f.p >= 2).map((f) => `P${f.p} ${f.title}`);
  const verdict = onHead ? (/APPROVE/.test(onHead.body.split('\n')[0]) && !findings.length ? 'approve' : 'changes') : null;
  const headAt = head?.committedDate ?? '';
  const requested = Boolean(REQUEST) && pr.comments.nodes.some((c) => REQUEST_RE.test(c.body) && c.createdAt >= headAt);

  const actions = [];
  if (pr.mergeable === 'CONFLICTING') { actions.push(`conflicts with ${pr.baseRefName}`); }
  if (failed.static.length) { actions.push(`static checks failed: ${failed.static.join(', ')}`); }
  if (failed.test.length) { actions.push(`tests failed: ${failed.test.join(', ')}`); }
  if (openThreads.length) { actions.push(`${openThreads.length} unresolved thread(s): ${openThreads.map((t) => t.id).join(', ')}`); }
  if (verdict === 'changes') { actions.push(`${BOT} review on ${pr.headRefOid.slice(0, 8)} lists ${findings.length ? `finding(s) still to fix: ${findings.join('; ')}` : 'requested changes'}`); }
  if (useBot && !verdict && !requested) { actions.push(`no ${BOT} review requested on head ${pr.headRefOid.slice(0, 8)}`); }

  const waits = [];
  if (!started) { waits.push('CI not started on head'); }
  if (pending.static.length) { waits.push(`static checks running: ${pending.static.join(', ')}`); }
  if (useBot && !verdict && requested) { waits.push(`${BOT} review running`); }

  const state = actions.length ? 'red'
    : waits.length ? 'waiting'
      : pending.test.length ? 'yellow'
        : 'green';
  return {
    repo, number: pr.number, title: pr.title, url: pr.url, branch: pr.headRefName, base: pr.baseRefName,
    head: pr.headRefOid, draft: pr.isDraft, autoMerge: pr.autoMergeRequest ? { method: pr.autoMergeRequest.mergeMethod, enabledAt: pr.autoMergeRequest.enabledAt, by: pr.autoMergeRequest.enabledBy?.login } : null, additions: pr.additions, deletions: pr.deletions,
    state, actions, waits, testsRunning: pending.test, openThreads, minorFindings, pushedAt: headAt,
  };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const ri = args.indexOf('--repo');
  const repo = ri >= 0 ? args.splice(ri, 2)[1] : execFileSync('gh', ['repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner'], { encoding: 'utf8' }).trim();
  if (!args.length) {
    console.error('usage: pr-state.mjs [--repo owner/name] <pr-number|branch>...');
    process.exit(64);
  }
  for (const [i, pr] of fetchPrs(args, repo).entries()) {
    console.log(JSON.stringify(pr && pr.state === 'OPEN' ? classify(pr) : { ref: args[i], state: pr ? pr.state.toLowerCase() : 'none' }));
  }
}
