"""Pinned agents@4.0.1 fading.ts v2 direct TypeScript differential vectors."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from local_shell_mcp.webui import fading as f


def _vectors():
    path = Path(__file__).parent / 'fixtures' / 'webui_fading_v2_source_vectors.json.gz'
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        return json.load(handle)


@pytest.mark.parametrize('case', _vectors())
def test_source_fading_v2_exact_differential(case):
    x, expected = case['input'], case['expected']
    window, seed, cap = x['window'], x['seed'], x['maxToolResultChars']
    tokens, width, target, signals = x['rawTokens'], x['exchangeWidth'], x['targetChars'], x['signals']
    tier = f.seed_fading_tier(window, seed)
    actual = {
        'isFadingTier': f.is_fading_tier(seed),
        'isLegacyFadingTier': f.is_legacy_fading_tier(seed),
        'maxFadingRung': f.max_fading_rung(window),
        'budgetRung0': f.fading_budget_tokens(window, 0),
        'budgetRung3': f.fading_budget_tokens(window, 3),
        'seeded': tier,
        'caps': f.resolve_fading_caps(tier, cap),
        'rungResult': f.fading_rung_for_result_chars(window, target, cap),
        'rungBudget': f.fading_rung_for_budget(window, tokens, cap, width),
        'rungExchange': f.fading_rung_for_exchange_chars(window, target, cap),
        'resolved': f.resolve_fading_tier(tier, window, signals, cap),
        'informative': f.is_informative_fading_tier(tier, window),
    }
    assert actual == expected


def test_invalid_saved_v1_tiers_cannot_be_used_without_recalibration():
    assert f.is_legacy_fading_tier({'v': 1, 'budgetTokens': 1000, 'masked': False})
    assert not f.is_fading_tier({'v': 1, 'budgetTokens': 1000, 'masked': False})
    assert f.seed_fading_tier(1000, {'v': 1, 'budgetTokens': 400, 'masked': True}) == {
        'v': 2, 'budgetTokens': 1000, 'masked': False}
    for bad in [None, '', [], {}, {'v': True, 'budgetTokens': 1000, 'masked': False},
                {'v': 2, 'budgetTokens': 0, 'masked': False},
                {'v': 2, 'budgetTokens': float('inf'), 'masked': False},
                {'v': 2, 'budgetTokens': 1000, 'masked': 1},
                {'v': 2, 'budgetTokens': 1000, 'masked': False, 'latched': False}]:
        assert f.seed_fading_tier(1000, bad) == f.create_fading_tier(1000)
