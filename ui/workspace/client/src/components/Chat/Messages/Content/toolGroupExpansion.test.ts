import { shouldExpandToolGroup } from './toolGroupExpansion';

const defaults = {
  autoExpand: false,
  withinActivityPhase: false,
  hasPendingApproval: false,
  hasPendingAuthRequest: false,
};

describe('tool group default disclosure', () => {
  it('starts collapsed with the default preference, even for a standalone group', () => {
    expect(shouldExpandToolGroup(defaults)).toBe(false);
    expect(shouldExpandToolGroup({ ...defaults, withinActivityPhase: true })).toBe(false);
  });

  it('honors the explicit auto-expand preference outside nested phases', () => {
    expect(shouldExpandToolGroup({ ...defaults, autoExpand: true })).toBe(true);
    expect(
      shouldExpandToolGroup({ ...defaults, autoExpand: true, withinActivityPhase: true }),
    ).toBe(false);
  });

  it.each(['hasPendingApproval', 'hasPendingAuthRequest'] as const)(
    'opens for a pending user action: %s',
    (pendingField) => {
      expect(shouldExpandToolGroup({ ...defaults, [pendingField]: true })).toBe(true);
      expect(
        shouldExpandToolGroup({ ...defaults, withinActivityPhase: true, [pendingField]: true }),
      ).toBe(true);
    },
  );
});
