// Loads the *unchanged pinned original* LibreChat triggers/backoff.ts through Bun.
import { waitingRetryAfter } from './trigger_backoff_source.ts';
const parts = [];
for await (const chunk of process.stdin) parts.push(chunk);
const inputs = JSON.parse(Buffer.concat(parts).toString('utf8'));
process.stdout.write(JSON.stringify(inputs.map(({since,now}) => waitingRetryAfter(since, now))));
