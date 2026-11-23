import { ContentTypes } from 'librechat-data-provider';
import type { TMessageContentParts } from 'librechat-data-provider';
import { rewindStreamContent } from './useStepHandler';

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
