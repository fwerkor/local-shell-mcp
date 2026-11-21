// Evaluate the exact unchanged pinned LibreChat detachedAction.ts parser code.
// Extract only its two pure exported parsers to avoid importing server DI.
import { readFileSync } from 'node:fs';
const upstream = readFileSync(new URL('./triggers/detachedAction.ts', import.meta.url), 'utf8');
const start = upstream.indexOf('const MAX_TERMINAL_RESULT_LENGTH');
const end = upstream.indexOf('interface DetachedActionOwner');
if (start === -1 || end <= start) throw Error('Pinned source parser boundaries changed');
const source = upstream.slice(start, end);
const transpiler = new Bun.Transpiler({ loader: 'ts', target: 'bun' });
const javascript = transpiler.transformSync(source);
const original = await import('data:text/javascript;base64,' + Buffer.from(javascript).toString('base64'));
if (process.env.LSM_ORACLE_DEBUG) process.stderr.write(JSON.stringify(Object.keys(original)) + '\n');
const chunks = []; for await (const chunk of process.stdin) chunks.push(chunk);
const cases = JSON.parse(Buffer.concat(chunks).toString('utf8'));
process.stdout.write(JSON.stringify(cases.map(([kind, value]) => kind === 'terminal'
  ? original.parseAgentEventDetachedTerminalEvidence(value) ?? null
  : original.parseAgentEventActorDetachedCompletion(value) ?? null)));
