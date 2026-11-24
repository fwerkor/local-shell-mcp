import { render, screen } from '@testing-library/react';
import About from './About';
import { useGetStartupConfig } from '~/data-provider';

jest.mock('~/data-provider', () => ({ useGetStartupConfig: jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/components/Messages/Content/CopyButton', () => ({
  __esModule: true,
  default: ({ label, onClick }: { label: string; onClick: () => void }) => (
    <button onClick={onClick}>{label}</button>
  ),
}));
jest.mock('copy-to-clipboard', () => jest.fn(() => true));

const mockedConfig = useGetStartupConfig as jest.Mock;

describe('About', () => {
  it('shows the runtime LSM version and hides unavailable build fields', () => {
    mockedConfig.mockReturnValue({ data: { lsmVersion: '9.8.7' } });
    render(<About />);
    expect(screen.getByText('9.8.7')).toBeInTheDocument();
    expect(screen.queryByText('com_nav_about_commit')).not.toBeInTheDocument();
    expect(screen.queryByText('com_nav_about_branch')).not.toBeInTheDocument();
    expect(screen.queryByText('com_nav_about_build_date')).not.toBeInTheDocument();
  });

  it('shows available source metadata', () => {
    mockedConfig.mockReturnValue({
      data: {
        lsmVersion: '6.0.1',
        buildInfo: {
          commit: 'abcdef0123456789',
          commitShort: 'abcdef01',
          branch: 'main',
          buildDate: '2026-11-23T08:00:00Z',
        },
      },
    });
    render(<About />);
    expect(screen.getByText('6.0.1')).toBeInTheDocument();
    expect(screen.getByText('abcdef01')).toBeInTheDocument();
    expect(screen.getByText('main')).toBeInTheDocument();
    expect(screen.getByText('2026-11-23 08:00:00 UTC')).toBeInTheDocument();
  });
});
