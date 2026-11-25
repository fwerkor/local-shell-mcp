import { render, screen } from '@testing-library/react';
import SkillsAccordion from './SkillsAccordion';

jest.mock('./SkillsSidePanel', () => ({
  __esModule: true,
  default: ({ className }: { className: string }) => (
    <div data-testid="skills-panel" className={className} />
  ),
}));

describe('SkillsAccordion', () => {
  it('renders the skills panel without an administrator footer or auth provider', () => {
    const { container } = render(<SkillsAccordion />);
    expect(screen.getByTestId('skills-panel')).toHaveClass('flex-1', 'min-h-0');
    expect(container.firstElementChild?.children).toHaveLength(1);
  });
});
