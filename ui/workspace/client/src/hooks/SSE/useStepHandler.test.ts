import { ContentTypes } from 'librechat-data-provider';
import type { TMessageContentParts } from 'librechat-data-provider';
import { insertGoalContinuation, rewindStreamContent } from './useStepHandler';

describe('rewindStreamContent', () => {
  it('retains the edited response prefix while rewinding only current-generation text', () => {
    const oldText = { type: ContentTypes.TEXT, text: 'Previously saved.' };
    const oldTool = { type: ContentTypes.TOOL_CALL, tool_call: { id: 'old-tool', name: 'run_shell' } };
    const freshText = { type: ContentTypes.TEXT, text: 'Checkpoint. Abandoned.' };
    const content = [oldText, oldTool, freshText] as TMessageContentParts[];

    const rewound = rewindStreamContent(content, 'Checkpoint. ', 2);
    expect(rewound).toEqual([oldText, oldTool, { ...freshText, text: 'Checkpoint. ' }]);
    expect(content[2]).toEqual(freshText);

    const cleared = rewindStreamContent(content, '', 2);
    expect(cleared[0]).toEqual(oldText);
    expect(cleared[1]).toEqual(oldTool);
    expect(cleared[2]).toEqual({ ...freshText, text: '' });
  });

  it('removes abandoned new text folded into the retained last text part', () => {
    const original = 'Retained prefix. ';
    const merged = { type: ContentTypes.TEXT, text: original + 'Checkpoint. Abandoned.' };
    const content = [merged] as TMessageContentParts[];

    expect(rewindStreamContent(content, 'Checkpoint. ', 1, original)).toEqual([
      { ...merged, text: original + 'Checkpoint. ' },
    ]);
    expect(rewindStreamContent(content, '', 1, original)).toEqual([
      { ...merged, text: original },
    ]);
    expect(content[0]).toBe(merged);
  });

  it('spends checkpoint text across a folded part and later text slots', () => {
    const oldText = { type: ContentTypes.TEXT, text: 'Kept.' };
    const oldTool = { type: ContentTypes.TOOL_CALL, tool_call: { id: 'previous' } };
    const folded = { type: ContentTypes.TEXT, text: 'Saved. Checkpoint. ' };
    const tool = { type: ContentTypes.TOOL_CALL, tool_call: { id: 'fresh' } };
    const next = { type: ContentTypes.TEXT, text: 'Recovered. Abandoned.' };
    const content = [oldText, oldTool, folded, tool, next] as TMessageContentParts[];

    const result = rewindStreamContent(content, 'Checkpoint. Recovered.', 3, 'Saved. ');
    expect(result).toEqual([
      oldText,
      oldTool,
      folded,
      tool,
      { ...next, text: 'Recovered.' },
    ]);
    expect(rewindStreamContent(content, '', 3, 'Saved. ')[2]).toEqual({
      ...folded,
      text: 'Saved. ',
    });
  });

  it('preserves sparse tool-slot indexes and Unicode text boundaries', () => {
    const content: TMessageContentParts[] = [];
    const tool = { type: ContentTypes.TOOL_CALL, tool_call: { id: 'tool-1' } };
    content[1] = tool as TMessageContentParts;
    content[2] = { type: ContentTypes.TEXT, text: '🚀 discarded' } as TMessageContentParts;

    const rewound = rewindStreamContent(content, '🚀');
    expect(0 in rewound).toBe(false);
    expect(rewound[1]).toEqual(tool);
    expect(rewound[2]).toEqual({ type: ContentTypes.TEXT, text: '🚀' });
  });
});

describe('insertGoalContinuation', () => {
  it('places the marker at its server slot and ignores duplicate SSE replay', () => {
    const prose = { type: ContentTypes.TEXT, text: 'Still working.' } as const;
    const marker = { type: ContentTypes.GOAL_CONTINUATION, id: 'goal:run:3' } as const;
    const content = [prose];
    const updated = insertGoalContinuation(content, marker.id, 1);
    expect(updated).toEqual([prose, marker]);
    expect(insertGoalContinuation(updated, marker.id, 1)).toBe(updated);
    expect(insertGoalContinuation(updated, 'stale', 0)).toBe(updated);
    expect(rewindStreamContent(updated, 'Still working.')).toEqual(updated);
  });

  it('preserves absolute content indexes and replaces only empty reservations', () => {
    const blank = { type: ContentTypes.TEXT, text: '' } as const;
    const updated = insertGoalContinuation([blank], 'goal:run:4', 0);
    expect(updated).toEqual([{ type: ContentTypes.GOAL_CONTINUATION, id: 'goal:run:4' }]);
    const sparse = insertGoalContinuation([], 'goal:run:5', 2);
    expect(0 in sparse).toBe(false);
    expect(sparse[2]?.type).toBe(ContentTypes.GOAL_CONTINUATION);
  });
});
