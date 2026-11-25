import { ContentTypes } from 'librechat-data-provider';
import type { TMessageContentParts } from 'librechat-data-provider';
import { groupActivityPhases } from './activityLabels';
import { groupSequentialToolCalls } from './groupToolCalls';

const think = (value: string): TMessageContentParts =>
  ({ type: ContentTypes.THINK, think: value }) as TMessageContentParts;
const text = (value: string, phase?: 'commentary' | 'final_answer'): TMessageContentParts =>
  ({ type: ContentTypes.TEXT, text: value, phase }) as TMessageContentParts;
const tool = (id: string): TMessageContentParts =>
  ({
    type: ContentTypes.TOOL_CALL,
    tool_call: { id, name: 'read', args: '{}' },
  }) as TMessageContentParts;
const label = (value: string, extra: Record<string, unknown> = {}): TMessageContentParts =>
  ({ type: ContentTypes.ACTIVITY_LABEL, activity_label: value, ...extra }) as TMessageContentParts;

const transcript = [
  think('Plan'),
  text('Checking.', 'commentary'),
  tool('one'),
  label('Read first file'),
  think('Next'),
  text('Found it.', 'commentary'),
  tool('two'),
  label('Read second file'),
  think('Finish'),
  text('Done.', 'final_answer'),
];

describe('visible agent prose', () => {
  it('never places commentary inside a labeled tool group', () => {
    const groups = groupSequentialToolCalls(transcript.map((part, idx) => ({ part, idx })));
    expect(
      groups
        .filter((group) => group.type === 'single' && group.part.part.type === ContentTypes.TEXT)
        .map((group) => group.type === 'single' && group.part.idx),
    ).toEqual([1, 5, 9]);
    for (const group of groups) {
      if (group.type === 'tool-group') {
        expect(group.parts.every(({ part }) => part.type !== ContentTypes.TEXT)).toBe(true);
      }
    }
  });

  it.each([false, true])('never folds prose in synthesized phases (live=%s)', (live) => {
    const segments = groupActivityPhases(transcript.slice(0, 8), undefined, live);
    if (segments == null) {
      return; // No phase fold is needed when every activity is separated by prose.
    }
    expect(segments.flatMap((segment) => segment.contentIndices)).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
    for (const segment of segments) {
      if (segment.type === 'phase') {
        expect(segment.content.every((part) => part?.type !== ContentTypes.TEXT)).toBe(true);
      }
    }
  });

  it('keeps legacy server phase ranges containing prose open and ordered', () => {
    const parts = [
      ...transcript.slice(0, 8),
      label('Read both files', {
        activity_label_type: 'phase',
        activity_start_index: 0,
        activity_end_index: 8,
      }),
      text('Done.'),
    ];
    const segments = groupActivityPhases(parts);
    expect(segments).toBeDefined();
    expect(segments?.flatMap((segment) => segment.contentIndices)).toEqual([
      0, 1, 2, 3, 4, 5, 6, 7, 9,
    ]);
    expect(
      segments
        ?.filter((segment) => segment.type === 'phase')
        .every((segment) => segment.content.every((part) => part?.type !== ContentTypes.TEXT)),
    ).toBe(true);
  });

  it('still folds a reasoning/tool-only live span', () => {
    const segments = groupActivityPhases([think('Plan'), tool('one')], undefined, true);
    expect(segments?.[0]?.type).toBe('phase');
  });
});
