"""Source-pinned v2 context fading tier ladder and tool exchange caps.

@librechat/agents@4.0.1: src/messages/fading.ts + src/utils/truncation.ts.
Pure tier functions never mutate source history; provider projections can use
caps while SQLite retains original tool outputs for later summarization.
"""
from __future__ import annotations

import math

FADING_TIER_VERSION = 2
PRESSURE_THRESHOLD_MASKING = .8
FADING_MIN_BUDGET_TOKENS = 170
MASKED_RESULT_MIN_CHARS = 300
HARD_MAX_TOOL_RESULT_CHARS = 400_000
HARD_MAX_TOOL_CALL_INPUT_CHARS = 200_000
MIN_JSON_VALUE_CHARS = 4


def _floor(window: int) -> int:
    return min(FADING_MIN_BUDGET_TOKENS, window)


def create_fading_tier(window: int) -> dict:
    return {'v': 2, 'budgetTokens': window, 'masked': False}


def _of_version(value: object, version: int) -> bool:
    if not isinstance(value, dict):
        return False
    budget = value.get('budgetTokens')
    latched = value.get('latched')
    return (type(value.get('v')) is int and value['v'] == version
            and type(budget) in (int, float) and math.isfinite(budget) and budget > 0
            and type(value.get('masked')) is bool and (latched is None or latched is True))


def is_fading_tier(value: object) -> bool:
    return _of_version(value, 2)


def is_legacy_fading_tier(value: object) -> bool:
    return _of_version(value, 1)


def max_fading_rung(window: int) -> int:
    floor = _floor(window)
    return max(0, math.ceil(math.log2(window / floor))) if floor > 0 else 0


def fading_budget_tokens(window: int, rung: int) -> int:
    return max(_floor(window), math.floor(window / (2 ** rung)))


def seed_fading_tier(window: int, seed: object = None) -> dict:
    if not is_fading_tier(seed):
        return create_fading_tier(window)
    budget = max(_floor(window), min(seed['budgetTokens'], window))
    informative = (seed.get('latched') is True or seed['masked'] or
                   budget != seed['budgetTokens'] or budget < window)
    return {'v': 2, 'budgetTokens': budget, 'masked': seed['masked'], 'latched': True} if informative else create_fading_tier(window)


def max_tool_result_chars(window: int | None) -> int:
    return min(math.floor(window * .3) * 4, HARD_MAX_TOOL_RESULT_CHARS) if window and window > 0 else HARD_MAX_TOOL_RESULT_CHARS


def max_tool_input_chars(window: int | None) -> int:
    return max(MIN_JSON_VALUE_CHARS, min(math.floor(window * .15) * 4, HARD_MAX_TOOL_CALL_INPUT_CHARS)) if window and window > 0 else HARD_MAX_TOOL_CALL_INPUT_CHARS


def fading_rung_for_result_chars(window: int, target: int, max_result: int | None = None) -> int:
    deepest = max_fading_rung(window)
    for rung in range(deepest):
        chars = max_tool_result_chars(fading_budget_tokens(window, rung))
        if max_result is not None:
            chars = min(chars, max_result)
        if chars <= target:
            return rung
    return deepest


def fading_rung_for_budget(window: int, raw_tokens: float, max_result: int | None = None,
                            exchange_width: float = 1) -> int:
    if not raw_tokens > 0:
        return 0
    target = math.floor(raw_tokens) * 4
    width = max(1, math.floor(exchange_width))
    deepest = max_fading_rung(window)
    for rung in range(deepest):
        size = fading_budget_tokens(window, rung)
        result_chars = max_tool_result_chars(size)
        if max_result is not None:
            result_chars = min(result_chars, max_result)
        if width * (result_chars + max_tool_input_chars(size)) <= target:
            return rung
    return deepest


def fading_rung_for_exchange_chars(window: int, target: int, max_result: int | None = None) -> int:
    deepest = max_fading_rung(window)
    for rung in range(deepest):
        size = fading_budget_tokens(window, rung)
        result_chars = max_tool_result_chars(size)
        if max_result is not None:
            result_chars = min(result_chars, max_result)
        if result_chars + max_tool_input_chars(size) <= target:
            return rung
    return deepest


def resolve_fading_caps(tier: dict, max_result: int | None = None) -> dict:
    budget = tier['budgetTokens']
    chars = max_tool_result_chars(budget)
    if max_result is not None:
        chars = min(chars, max_result)
    consumed = min(chars, max(MASKED_RESULT_MIN_CHARS, math.floor(chars * .1))) if tier['masked'] else chars
    return {'budgetTokens': budget, 'resultChars': chars, 'consumedChars': consumed,
            'inputChars': max_tool_input_chars(budget)}


def resolve_fading_tier(tier: dict, window: int, signals: dict,
                        max_result: int | None = None) -> dict:
    fit = fading_rung_for_budget(window, signals['effectiveRawTokens'], max_result,
                                 signals.get('toolExchangeWidth', 1))
    pressure = signals['contextPressure']
    band = 0 if signals['summarizationEnabled'] else (
        4 if pressure >= .99 else 2 if pressure >= .9 else 1 if pressure >= .85 else 0)
    rung = min(max_fading_rung(window), max(fit + band, signals.get('minRung', 0)))
    budget = min(tier['budgetTokens'], fading_budget_tokens(window, rung))
    masked = tier['masked'] or pressure >= PRESSURE_THRESHOLD_MASKING
    if budget == tier['budgetTokens'] and masked == tier['masked']:
        return tier
    return {'v': 2, 'budgetTokens': budget, 'masked': masked, 'latched': True}


def is_informative_fading_tier(tier: dict | None, window: int | None) -> bool:
    return bool(tier and (tier.get('latched') is True or tier.get('masked')
                          or (window is not None and window > 0 and tier['budgetTokens'] < window)))
