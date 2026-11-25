import { render, screen } from '@testing-library/react';
import Footer from './Footer';

jest.mock('~/data-provider', () => ({ useGetStartupConfig: () => ({}) }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));

describe('Footer branding', () => {
  it('uses the LSM project link when no custom footer is configured', () => {
    render(<Footer startupConfig={{}} />);
    expect(screen.getByRole('link', { name: 'local-shell-mcp' })).toHaveAttribute(
      'href',
      'https://github.com/fwerkor/local-shell-mcp',
    );
  });

  it('preserves operator-provided content', () => {
    render(<Footer startupConfig={{ customFooter: 'Custom workspace' }} />);
    expect(screen.getByText('Custom workspace')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'local-shell-mcp' })).not.toBeInTheDocument();
  });

  it('hides the default footer in configured-only mode', () => {
    render(<Footer startupConfig={{}} configuredOnly />);
    expect(screen.queryByRole('link', { name: 'local-shell-mcp' })).not.toBeInTheDocument();
  });
});
