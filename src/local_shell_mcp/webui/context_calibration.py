"""Source-pinned cumulative provider token calibration.

@librechat/agents@4.0.1 messages/prune.ts, lines 123-137 and 2850-2950.
Measurements must be confirmed provider input usage, not estimated billed
usage; no observation means the calibration ratio remains unchanged.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

MIN_RATIO = 0.5
MAX_RATIO = 5.0
MAX_CUMULATIVE_TOKENS = 10**12


def clamp_calibration_ratio(value: float) -> float:
    if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value):
        return 1.0
    return max(MIN_RATIO, min(MAX_RATIO, float(value)))


@dataclass(frozen=True)
class TokenCalibration:
    cumulative_raw_sent: int = 0
    cumulative_provider_reported: int = 0
    ratio: float = 1.0

    def observe(self, *, provider_input_tokens: int, raw_sent_this_turn: int,
                instruction_overhead: int) -> TokenCalibration:
        """Update cumulative ratio if observed tokens pass source safety gates."""
        if (any(type(value) is not int or value < 0 or value > MAX_CUMULATIVE_TOKENS
                for value in (provider_input_tokens, raw_sent_this_turn, instruction_overhead))
                or raw_sent_this_turn <= 0):
            return self
        provider_message_tokens = max(0, provider_input_tokens - instruction_overhead)
        minimum_comparable = instruction_overhead + raw_sent_this_turn * MIN_RATIO
        if provider_message_tokens <= 0 or provider_input_tokens < minimum_comparable:
            return self
        raw = self.cumulative_raw_sent + raw_sent_this_turn
        observed = self.cumulative_provider_reported + provider_message_tokens
        if max(raw, observed) > MAX_CUMULATIVE_TOKENS or raw <= 0:
            return self
        return TokenCalibration(raw, observed, clamp_calibration_ratio(observed / raw))

    @classmethod
    def from_dict(cls, value: object) -> TokenCalibration:
        if not isinstance(value, dict):
            return cls()
        raw = value.get('cumulativeRawSent')
        observed = value.get('cumulativeProviderReported')
        if (type(raw) is not int or type(observed) is not int
                or not 0 <= raw <= MAX_CUMULATIVE_TOKENS
                or not 0 <= observed <= MAX_CUMULATIVE_TOKENS):
            return cls()
        return cls(raw, observed, clamp_calibration_ratio(observed / raw) if raw else 1.0)

    def to_dict(self) -> dict:
        return {'cumulativeRawSent': self.cumulative_raw_sent,
                'cumulativeProviderReported': self.cumulative_provider_reported,
                'calibrationRatio': self.ratio}
