// Settings shared with the Python hooks (hooks/lead_lib.py). The watcher inherits CLAUDE_PLUGIN_OPTION_* from the hook
// that started it. A command run through the Bash tool doesn't, so fall back to the copy SessionStart writes.
import { existsSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const CONFIG_HOME = process.env.CLAUDE_CONFIG_DIR ?? join(homedir(), '.claude');
export const DATA = join(CONFIG_HOME, 'tech-lead');

const DEFAULTS = {
  owner_name: 'the owner',
  review_bot: '',
  review_request: '',
  tracker_publisher: 'none',
  repos_dir: '~/workspace',
};

const readJson = (p) => {
  try { return JSON.parse(readFileSync(p, 'utf8')); } catch { return {}; }
};
const saved = readJson(join(DATA, 'config.json'));

export function option(key) {
  const env = process.env[`CLAUDE_PLUGIN_OPTION_${key.toUpperCase()}`];
  return env ?? saved[key] ?? DEFAULTS[key];
}

export const ownerName = () => option('owner_name') || DEFAULTS.owner_name;
export const expandHome = (p) => p.replace(/^~(?=\/|$)/, homedir());

// CI check names belong to the user's repos, so their copy replaces the plugin's empty default outright.
const personal = join(DATA, 'checks.json');
const CHECKS = readJson(existsSync(personal) ? personal : join(dirname(fileURLToPath(import.meta.url)), 'checks.json'));
export const checksFor = (repo) => CHECKS[repo] ?? CHECKS.default ?? { ignore: [], test: [] };
