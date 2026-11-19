import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

// A worker is live from its spawn or a SendMessage to it until its next task-notification or TaskStop.
export function liveOwners(leadDir) {
  const session = join(leadDir, 'session.json');
  if (!existsSync(session)) { return new Set(); }
  const { transcript_path: path } = JSON.parse(readFileSync(session, 'utf8'));
  if (!path || !existsSync(path)) { return new Set(); }

  const nameByToolUse = new Map();
  const nameByTask = new Map();
  const live = new Map();
  for (const line of readFileSync(path, 'utf8').split('\n')) {
    if (!line) { continue; }
    let row;
    try { row = JSON.parse(line); } catch { continue; }
    const content = row.message?.content;
    if (row.type === 'assistant' && Array.isArray(content)) {
      for (const c of content) {
        if (c.type !== 'tool_use') { continue; }
        if (c.name === 'Agent' && c.input?.name) { nameByToolUse.set(c.id, c.input.name); live.set(c.input.name, true); }
        if (c.name === 'SendMessage' && c.input?.to) {
          const name = nameByTask.get(c.input.to) ?? c.input.to;
          nameByToolUse.set(c.id, name);
          live.set(name, true);
        }
        if (c.name === 'TaskStop' && c.input?.task_id) { const n = nameByTask.get(c.input.task_id); if (n) { live.set(n, false); } }
      }
    }
    if (row.type === 'user' || row.type === 'queue-operation') {
      const raw = row.type === 'queue-operation' ? row.content : content;
      const parts = typeof raw === 'string' ? [raw] : (raw ?? []).map((c) => (typeof c.content === 'string' ? c.content : c.text ?? JSON.stringify(c.content ?? '')));
      for (const text of parts) {
        const asyncId = text.match(/agentId: (\w+)/);
        for (const m of text.matchAll(/<task-notification>([\s\S]*?)<\/task-notification>/g)) {
          const taskId = m[1].match(/<task-id>(\w+)<\/task-id>/)?.[1];
          const toolUse = m[1].match(/<tool-use-id>(\w+)<\/tool-use-id>/)?.[1];
          const name = nameByTask.get(taskId) ?? nameByToolUse.get(toolUse);
          if (name) { live.set(name, false); if (taskId) { nameByTask.set(taskId, name); } }
        }
        for (const m of text.matchAll(/<teammate-message teammate_id="([^"]+)"[^>]*>\s*\{"type":"idle_notification"/g)) {
          live.set(nameByTask.get(m[1]) ?? m[1], false);
        }
        if (asyncId && Array.isArray(content)) {
          const id = content.find((c) => c.tool_use_id)?.tool_use_id;
          const name = nameByToolUse.get(id);
          if (name) { nameByTask.set(asyncId[1], name); }
        }
      }
    }
  }
  return new Set([...live].filter(([, v]) => v).map(([k]) => k));
}
