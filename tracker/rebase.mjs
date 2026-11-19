#!/usr/bin/env node
// Usage: node rebase.mjs <lead-dir> [--dry-run]
// Rebases every open unit PR that conflicts with its base branch, without a checkout, and force-pushes it with a lease on the
// head it read. A rebase that hits a conflict is left alone and recorded in rebase-log.json for the owner.
// A unit's `repo` overrides state.repo. Each repo rebases in state.repoDirs[repo], else <repos_dir setting>/<name>
// (REBASE_REPO_DIR overrides it for state.repo). With no checkout whose origin is that repo, the conflict is recorded as
// `no-checkout` and reported to the owner as a blocker.
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { checksFor, fetchPrs, prKey, unitRepo } from './pr-state.mjs';
import { expandHome, option } from './config.mjs';

const gitIn = (dir, ...args) => execFileSync('git', ['-C', dir, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
const gh = (...args) => execFileSync('gh', args, { encoding: 'utf8' }).trim();

export function checkoutFor(state, repo) {
  const fallback = repo === state.repo && process.env.REBASE_REPO_DIR ? process.env.REBASE_REPO_DIR : join(expandHome(option('repos_dir')), repo.split('/')[1]);
  const dir = expandHome(state.repoDirs?.[repo] ?? fallback);
  try {
    return gitIn(dir, 'remote', 'get-url', 'origin').replace(/\.git$/, '').endsWith(`/${repo}`) ? dir : null;
  } catch { return null; }
}

// Open unit PRs that conflict with their base, in the shape classify() returns.
function conflictingUnitPrs(state) {
  const units = state.units.filter((u) => u.pr && u.status !== 'merged' && u.status !== 'dropped');
  const repos = [...new Set(units.map((u) => unitRepo(state, u)))];
  return repos.flatMap((repo) => fetchPrs(units.filter((u) => unitRepo(state, u) === repo).map((u) => String(u.pr)), repo)
    .filter((pr) => pr?.state === 'OPEN' && pr.mergeable === 'CONFLICTING')
    .map((pr) => ({ repo, number: pr.number, conflicting: true, base: pr.baseRefName, branch: pr.headRefName, head: pr.headRefOid })));
}

// `prs` is the watcher's own classified view, so a tick makes no GitHub calls here unless a PR conflicts.
export function rebaseConflicting(dir, { dryRun = false, prs = null } = {}) {
  const state = JSON.parse(readFileSync(join(dir, 'state.json'), 'utf8'));
  const logPath = join(dir, 'rebase-log.json');
  const log = existsSync(logPath) ? JSON.parse(readFileSync(logPath, 'utf8')) : {};
  const results = [];
  for (const c of prs ?? conflictingUnitPrs(state)) {
    const unit = state.units.find((u) => unitRepo(state, u) === c.repo && String(u.pr) === String(c.number));
    if (!c.conflicting || !unit || unit.status === 'merged' || unit.status === 'dropped') { continue; }
    const repo = c.repo;
    const pr = { number: c.number, baseRefName: c.base, headRefName: c.branch, headRefOid: c.head };
    const base = `origin/${pr.baseRefName}`;
    const branch = pr.headRefName;
    const head = pr.headRefOid;
    const key = prKey(state, repo, pr.number);
    if (log[key]?.head === head && ['conflict', 'no-checkout'].includes(log[key]?.result)) {
      results.push({ repo, number: pr.number, result: log[key].result, files: log[key].files, skipped: true });
      continue;
    }
    const dir = checkoutFor(state, repo);
    if (!dir) {
      const entry = { head, result: 'no-checkout', files: [], at: new Date().toISOString() };
      if (!dryRun) { log[key] = entry; }
      results.push({ repo, number: pr.number, owner: unit.owner, ...entry });
      continue;
    }
    const git = (...args) => gitIn(dir, ...args);
    git('fetch', '--quiet', 'origin', `+refs/heads/${pr.baseRefName}:refs/remotes/origin/${pr.baseRefName}`, `+refs/heads/${branch}:refs/remotes/origin/${branch}`);
    const fetched = git('rev-parse', `refs/remotes/origin/${branch}`);
    if (fetched !== head) { continue; }
    let entry;
    try {
      const out = git('replay', `--ref=refs/rebase-bot/${branch}`, '--ref-action=print', '--onto', base, `${base}..${head}`);
      const newHead = out.split('\n').map((l) => l.split(' ')).find((p) => p[0] === 'update')?.[2];
      if (!newHead) { throw new Error(`git replay printed no update: ${out}`); }
      if (!dryRun) {
        git('push', `--force-with-lease=refs/heads/${branch}:${head}`, 'origin', `${newHead}:refs/heads/${branch}`);
        if (option('review_request') && checksFor(repo).reviewBot !== false) { gh('pr', 'comment', String(pr.number), '--repo', repo, '--body', option('review_request')); }
      }
      entry = { head: newHead, from: head, result: dryRun ? 'would-rebase' : 'rebased', at: new Date().toISOString() };
    } catch (e) {
      let files = [];
      try { git('merge-tree', '--write-tree', '--name-only', '--no-messages', base, head); } catch (m) {
        files = (m.stdout ?? '').split('\n').slice(1).filter(Boolean);
      }
      entry = { head, result: 'conflict', files, at: new Date().toISOString() };
    }
    if (!dryRun) { log[key] = entry; }
    results.push({ repo, number: pr.number, owner: unit.owner, ...entry });
  }
  if (!dryRun) { writeFileSync(logPath, JSON.stringify(log, null, 2)); }
  return results;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const args = process.argv.slice(2);
  const dir = resolve(args.find((a) => !a.startsWith('--')) ?? '.');
  console.log(JSON.stringify(rebaseConflicting(dir, { dryRun: args.includes('--dry-run') }), null, 2));
}
