import { fireEvent, render, screen, within } from '@testing-library/react';
import { Provider } from 'jotai';
import type { TokenUsageView } from '~/hooks/Chat/useTokenUsage';
import { EMPTY_BRANCH, EMPTY_USAGE } from '~/utils/tokens';
import Breakdown from './Breakdown';

jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
}));
jest.mock('~/store/usage', () => ({
  contextBreakdownExpandedAtom: require('jotai').atom(false),
}));

const view: TokenUsageView = {
  usedTokens: 610,
  maxTokens: 1000,
  percent: 61,
  isEstimate: false,
  providerInputTokens: 600,
  providerOutputTokens: 10,
  cacheRead: 450,
  snapshotActive: true,
  snapshot: {
    anchorMessageId: 'message',
    breakdown: {
      maxContextTokens: 1000,
      instructionTokens: 100,
      systemMessageTokens: 50,
      dynamicInstructionTokens: 0,
      toolSchemaTokens: 50,
      summaryTokens: 0,
      messageTokens: 400,
      toolMessageTokens: 200,
      toolMessageTokenCounts: { demo: 100 },
      toolCount: 1,
      messageCount: 4,
      availableForMessages: 900,
    },
  },
  branchTotals: EMPTY_BRANCH,
  branchUsage: EMPTY_USAGE,
  totalUsage: EMPTY_USAGE,
  hasUsage: false,
  branchCost: 0,
  totalCost: 0,
  liveTokens: 0,
  estimatedTokens: 0,
  overheadTokens: 0,
  messageTokens: 0,
  messagesPruned: false,
  toolMessageTokenCounts: { demo: 100 },
};

function panel(next: TokenUsageView) {
  return (
    <Provider>
      <Breakdown view={next} showCost={false} />
    </Provider>
  );
}

describe('unified context usage', () => {
  it('keeps exact request totals visible while the estimated breakdown expands', () => {
    render(panel(view));
    const overview = within(screen.getByTestId('context-overview'));
    expect(overview.getByText('75%')).toBeInTheDocument();
    expect(overview.getByText('600')).toBeInTheDocument();
    expect(screen.queryByText('com_ui_context_messages')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('context-breakdown-toggle'));
    const detail = within(screen.getByTestId('context-breakdown'));
    expect(detail.getByText('com_ui_context_messages')).toBeInTheDocument();
    expect(detail.getAllByText('(40%)', { selector: 'span' })).toHaveLength(2);
    fireEvent.click(detail.getByRole('button', { name: /com_ui_context_tool_calls/ }));
    expect(detail.getByText('demo')).toBeInTheDocument();
    expect(overview.getByText('600')).toBeInTheDocument();
  });

  it('distinguishes an explicit zero cache hit from missing telemetry', () => {
    const { rerender } = render(panel({ ...view, cacheRead: 0 }));
    expect(within(screen.getByTestId('context-overview')).getByText('0%')).toBeInTheDocument();
    rerender(panel({ ...view, cacheRead: undefined }));
    expect(within(screen.getByTestId('context-overview')).getByText('—')).toBeInTheDocument();
  });

  it('retains the overview in the estimate-only fallback', () => {
    render(
      panel({
        ...view,
        snapshot: null,
        snapshotActive: false,
        isEstimate: true,
        providerInputTokens: undefined,
        providerOutputTokens: undefined,
        cacheRead: undefined,
        liveTokens: 10,
        messageTokens: 600,
      }),
    );
    expect(within(screen.getByTestId('context-overview')).getByText('600')).toBeInTheDocument();
    expect(within(screen.getByTestId('context-overview')).getByText('—')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('context-breakdown-toggle'));
    expect(screen.getByTestId('context-estimate')).toBeInTheDocument();
  });
});
