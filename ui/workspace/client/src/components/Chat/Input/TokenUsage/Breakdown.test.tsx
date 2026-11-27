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
  recordedUsage: {
    inputTokens: 1500,
    outputTokens: 125,
    cacheReadTokens: 900,
    cacheKnownInputTokens: 1500,
    calls: 2,
  },
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

describe('separate cumulative and context usage', () => {
  it('shows cumulative usage independently of the window and one persistent meter', () => {
    render(panel(view));
    const totals = within(screen.getByTestId('token-usage-totals'));
    expect(totals.getByText('60%')).toBeInTheDocument();
    expect(totals.getByText('125')).toBeInTheDocument();
    expect(screen.queryByText('com_ui_context_messages')).not.toBeInTheDocument();
    expect(screen.getAllByRole('progressbar')).toHaveLength(1);
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '61');

    fireEvent.click(screen.getByTestId('context-breakdown-toggle'));
    const detail = within(screen.getByTestId('context-breakdown'));
    expect(detail.getByText('com_ui_context_messages')).toBeInTheDocument();
    expect(detail.getAllByText('(20%)', { selector: 'span' })).toHaveLength(2);
    expect(detail.getByText('(39%)')).toBeInTheDocument();
    expect(detail.getByText('(11%)')).toBeInTheDocument();
    expect(screen.getAllByRole('progressbar')).toHaveLength(1);
    fireEvent.click(detail.getByRole('button', { name: /com_ui_context_tool_calls/ }));
    expect(detail.getByText('demo')).toBeInTheDocument();
    expect(totals.getByText('60%')).toBeInTheDocument();
  });

  it('distinguishes explicit zero cache hits from incomplete telemetry', () => {
    const recordedUsage = { ...view.recordedUsage!, cacheReadTokens: 0 };
    const { rerender } = render(panel({ ...view, recordedUsage }));
    expect(within(screen.getByTestId('token-usage-totals')).getByText('0%')).toBeInTheDocument();
    rerender(panel({ ...view, recordedUsage: { ...recordedUsage, cacheKnownInputTokens: 600 } }));
    expect(within(screen.getByTestId('token-usage-totals')).getByText('—')).toBeInTheDocument();
  });

  it('never substitutes estimated context counts for missing usage', () => {
    render(
      panel({
        ...view,
        recordedUsage: null,
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
    expect(within(screen.getByTestId('token-usage-totals')).getAllByText('—')).toHaveLength(3);
    fireEvent.click(screen.getByTestId('context-breakdown-toggle'));
    expect(screen.getByTestId('context-estimate')).toBeInTheDocument();
    expect(screen.getAllByRole('progressbar')).toHaveLength(1);
  });
});
