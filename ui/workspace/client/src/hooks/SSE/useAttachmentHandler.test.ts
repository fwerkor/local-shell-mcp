import { Tools } from 'librechat-data-provider';
import type { TAttachment } from 'librechat-data-provider';
import { uiResourceSnapshotKeyOf, upsertUiResourceSnapshot } from './useAttachmentHandler';

const resource = (toolCallId: string, resourceId: string, text = 'before'): TAttachment => ({
  type: Tools.ui_resources,
  messageId: 'response-1',
  conversationId: 'conversation-1',
  toolCallId,
  ui_resources: [{ resourceId, uri: `ui://${resourceId}`, text }],
});

describe('MCP UI resource SSE reconnect', () => {
  it('upserts a replayed resource instead of appending a second interactive card', () => {
    const prior = resource('tool-1', 'widget-1');
    const replay = resource('tool-1', 'widget-1', 'updated');
    const replaced = upsertUiResourceSnapshot([prior], replay);
    expect(replaced).toEqual([replay]);
    expect(replaced).toHaveLength(1);
    expect(uiResourceSnapshotKeyOf(prior)).toBe(uiResourceSnapshotKeyOf(replay));
  });

  it('keeps distinct tool occurrences and resources separate', () => {
    const prior = resource('tool-1', 'widget-1');
    expect(upsertUiResourceSnapshot([prior], resource('tool-2', 'widget-1'))).toBeNull();
    expect(upsertUiResourceSnapshot([prior], resource('tool-1', 'widget-2'))).toBeNull();
    expect(uiResourceSnapshotKeyOf({ ...prior, ui_resources: [] })).toBeUndefined();
  });
});
