import type { Agents, MemoryArtifact } from 'librechat-data-provider';
import { getMemoryApiErrorMessage, isMemoryMutation, isMemoryToolMutation } from './memory';

describe('getMemoryApiErrorMessage', () => {
  it('preserves an actionable server error', () => {
    const error = Object.assign(new Error('Request failed'), {
      response: { data: { error: 'Value exceeds the configured character limit.' } },
    });

    expect(getMemoryApiErrorMessage(error, 'Error')).toBe(
      'Value exceeds the configured character limit.',
    );
  });

  it('falls back when the server does not provide an error', () => {
    expect(getMemoryApiErrorMessage(new Error('Request failed'), 'Error')).toBe('Error');
  });
});

describe('memory mutation refresh', () => {
  const artifact = (type: MemoryArtifact['type']): MemoryArtifact => ({ key: 'style', type });
  const call = (name: string, type: MemoryArtifact['type']) =>
    ({ name, artifact: { memory: artifact(type) } }) as Agents.ToolCall;

  it('recognizes successful memory attachments and ignores errors', () => {
    expect(isMemoryMutation(artifact('update'))).toBe(true);
    expect(isMemoryMutation(artifact('delete'))).toBe(true);
    expect(isMemoryMutation(artifact('error'))).toBe(false);
    expect(isMemoryMutation()).toBe(false);
  });

  it('recognizes completed inline memory tool mutations only', () => {
    expect(isMemoryToolMutation(call('set_memory', 'update'))).toBe(true);
    expect(isMemoryToolMutation(call('delete_memory', 'delete'))).toBe(true);
    expect(isMemoryToolMutation(call('set_memory', 'error'))).toBe(false);
    expect(isMemoryToolMutation(call('run_shell', 'update'))).toBe(false);
    expect(isMemoryToolMutation({ name: 'set_memory' } as Agents.ToolCall)).toBe(false);
    expect(isMemoryToolMutation()).toBe(false);
  });
});
