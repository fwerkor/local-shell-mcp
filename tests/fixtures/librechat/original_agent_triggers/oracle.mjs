// Executes the unmodified original LibreChat v0.8.8 production TypeScript.
import { createAgentTriggerEnvelope, getAgentTriggerIdempotencyKey } from './triggers/envelope.ts';
const parts = [];
for await (const chunk of process.stdin) parts.push(chunk);
const input = JSON.parse(Buffer.concat(parts).toString('utf8'));
const results = input.map((candidate) => {
  try {
    const envelope = createAgentTriggerEnvelope(candidate);
    return {key: getAgentTriggerIdempotencyKey(envelope), envelope};
  } catch (error) {
    return {error: error.message};
  }
});
process.stdout.write(JSON.stringify(results));
