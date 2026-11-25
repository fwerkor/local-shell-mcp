"""Sampling settings supported by all three native model transports."""
from __future__ import annotations

import math

_ALIASES = {
    "temperature": ("temperature",),
    "top_p": ("top_p", "topP"),
    "max_tokens": ("max_tokens", "maxTokens", "max_output_tokens", "maxOutputTokens"),
}


def validate_sampling(value: object, *, provider: str | None = None) -> dict:
    if not isinstance(value, dict) or value.keys() - _ALIASES.keys():
        raise ValueError("Invalid sampling parameters")
    result = {}
    for key, item in value.items():
        upper = {"temperature": 1 if provider == "anthropic" else 2, "top_p": 1, "max_tokens": 2_000_000}[key]
        if (type(item) not in (int, float) or not 0 <= item <= upper
                or not math.isfinite(item)
                or (key == "max_tokens" and (item < 1 or type(item) is not int))):
            raise ValueError(f"Invalid sampling parameter: {key}")
        result[key] = item
    return result


def validate_channel_sampling(value: object, channel: str | None) -> dict:
    result = validate_sampling(value)
    if result.get('temperature', 0) <= 1 or not channel:
        return result
    from .provider_profiles import profile

    return validate_sampling(result, provider=profile(channel)['provider'])


def merge_sampling(defaults: dict, overrides: dict) -> dict:
    """An explicit override wins, including legacy Agent aliases and zero."""
    sampling_aliases = {alias for aliases in _ALIASES.values() for alias in aliases}
    result = {**defaults, **{key: value for key, value in overrides.items()
                            if key not in sampling_aliases or value is not None}}
    for canonical, aliases in _ALIASES.items():
        for key in aliases:
            if overrides.get(key) is not None:
                for alias in aliases:
                    result.pop(alias, None)
                result[canonical] = overrides[key]
                break
    return result
