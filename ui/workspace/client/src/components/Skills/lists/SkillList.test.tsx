import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import type { TSkillSummary } from 'librechat-data-provider';
import SkillList from './SkillList';

let mockEnabled = false;
let mockLoading = false;
let mockError = false;

jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  useSkillActiveState: () => ({
    isActive: (skill: TSkillSummary) => skill._id !== 'example' || mockEnabled,
    isLoading: mockLoading,
    isError: mockError,
  }),
}));

jest.mock('react-vtree', () => ({ FixedSizeTree: () => null }), { virtual: true });

jest.mock('~/data-provider', () => ({
  useListSkillFilesQuery: () => ({ data: { files: [] } }),
}));

jest.mock('~/components/ui', () => ({
  Collapse: ({ open, children }: { open: boolean; children: React.ReactNode }) =>
    open ? <div>{children}</div> : null,
}));

jest.mock('~/utils', () => ({
  cn: (...values: unknown[]) => values.filter(Boolean).join(' '),
}));

const skill = {
  _id: 'example',
  name: 'example-skill',
  alwaysApply: true,
  fileCount: 0,
} as TSkillSummary;
const other = { ...skill, _id: 'other', name: 'other-skill', alwaysApply: false };

function Location() {
  return <output>{useLocation().pathname}</output>;
}

function List() {
  return (
    <MemoryRouter>
      <SkillList skills={[skill, other]} sectionOpen onSectionOpenChange={jest.fn()} />
      <Location />
    </MemoryRouter>
  );
}

beforeEach(() => {
  mockEnabled = false;
  mockLoading = false;
  mockError = false;
});

it('marks only disabled skills and keeps their management entry clickable', () => {
  render(<List />);
  const row = screen.getByRole('button', { name: /example-skill/ });
  expect(row).toHaveTextContent('com_ui_disabled');
  expect(row).toHaveClass('text-text-secondary');
  expect(screen.getByRole('button', { name: 'other-skill' })).not.toHaveTextContent(
    'com_ui_disabled',
  );
  expect(screen.queryByLabelText('com_ui_skills_always_apply_pin_title')).not.toBeInTheDocument();
  fireEvent.click(row);
  expect(screen.getByText('/skills/example')).toBeInTheDocument();
});

it('updates the same row when the shared state changes', () => {
  const { rerender } = render(<List />);
  mockEnabled = true;
  rerender(<List />);
  expect(screen.queryByText('com_ui_disabled')).not.toBeInTheDocument();
  expect(screen.getByLabelText('com_ui_skills_always_apply_pin_title')).toBeInTheDocument();
});

it.each(['loading', 'error'])('does not label unresolved state as disabled (%s)', (status) => {
  mockLoading = status === 'loading';
  mockError = status === 'error';
  render(<List />);
  expect(screen.queryByText('com_ui_disabled')).not.toBeInTheDocument();
});
