// Exact unchanged LibreChat source. No emulation of argument subset rules.
import { matchesExpectedAction } from './triggers/expectedAction.ts';
const chunks=[];for await (const c of process.stdin) chunks.push(c);
const data=JSON.parse(Buffer.concat(chunks).toString('utf8'));
process.stdout.write(JSON.stringify(data.map(([e,a])=>matchesExpectedAction(e,a))));
