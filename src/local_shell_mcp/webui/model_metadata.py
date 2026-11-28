"""Public model metadata fallback for recognized provider endpoints."""
from __future__ import annotations

import asyncio
import json
import logging
from time import monotonic
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

_CATALOG_URL = "https://models.dev/api.json"
_TTL = 6 * 60 * 60
_RETRY = 10 * 60
_MAX_BYTES = 16 * 1024 * 1024

# The protocol alone is not a provider identity. In particular a private
# OpenAI-compatible deployment can have a different effective context limit.
# Separate plan endpoints only when they identify the plan unambiguously.
_ENDPOINTS = {
    ("api.openai.com", "/v1"): ("openai", {"openai", "openai-responses"}),
    ("api.anthropic.com", "/v1"): ("anthropic", {"anthropic"}),
    ("generativelanguage.googleapis.com", "/v1beta"): ("google", {"google"}),
    ("generativelanguage.googleapis.com", "/v1"): ("google", {"google"}),
    ("openrouter.ai", "/api/v1"): ("openrouter", {"openai", "openai-responses"}),
    ("api.deepseek.com", ""): ("deepseek", {"openai"}),
    ("api.deepseek.com", "/v1"): ("deepseek", {"openai"}),
    ("api.x.ai", "/v1"): ("xai", {"openai", "openai-responses"}),
    ("api.mistral.ai", "/v1"): ("mistral", {"openai"}),
    ("api.groq.com", "/openai/v1"): ("groq", {"openai"}),
    ("api.together.xyz", "/v1"): ("togetherai", {"openai"}),
    ("api.cerebras.ai", "/v1"): ("cerebras", {"openai"}),
    ("api.fireworks.ai", "/inference/v1"): ("fireworks-ai", {"openai"}),
    ("api.moonshot.ai", "/v1"): ("moonshotai", {"openai"}),
    ("api.moonshot.cn", "/v1"): ("moonshotai-cn", {"openai"}),
    ("api.z.ai", "/api/paas/v4"): ("zai", {"openai"}),
    ("api.z.ai", "/api/coding/paas/v4"): ("zai-coding-plan", {"openai"}),
    ("dashscope-intl.aliyuncs.com", "/compatible-mode/v1"): ("alibaba", {"openai"}),
    ("integrate.api.nvidia.com", "/v1"): ("nvidia", {"openai"}),
    ("api.deepinfra.com", "/v1/openai"): ("deepinfra", {"openai"}),
    ("api.sambanova.ai", "/v1"): ("sambanova", {"openai"}),
    ("api.perplexity.ai", ""): ("perplexity", {"openai"}),
    ("api.stepfun.com", "/v1"): ("stepfun", {"openai"}),
    ("router.huggingface.co", "/v1"): ("huggingface", {"openai"}),
    ("opencode.ai", "/inference/openai/v1"): ("opencode", {"openai"}),
    ("opencode.ai", "/zen/v1"): ("opencode", {"openai"}),
    ("opencode.ai", "/inference/go/openai/v1"): ("opencode-go", {"openai"}),
    ("opencode.ai", "/zen/go/v1"): ("opencode-go", {"openai"}),
}
_PROVIDERS = frozenset(provider for provider, _ in _ENDPOINTS.values())


def _provider(kind: str, base: str) -> str | None:
    try:
        url = urlsplit(base)
        if (url.scheme != "https" or url.port not in (None, 443)
                or url.username is not None or url.password is not None
                or url.query or url.fragment):
            return None
        entry = _ENDPOINTS.get((url.hostname, url.path.rstrip("/")))
    except ValueError:
        return None
    return entry[0] if entry and kind in entry[1] else None


def _parse_catalog(data: dict) -> dict[str, dict[str, int]]:
    if not isinstance(data, dict):
        raise ValueError("Invalid public model catalog")
    result = {}
    for provider in _PROVIDERS:
        entry = data.get(provider)
        models = entry.get("models") if isinstance(entry, dict) else None
        if not isinstance(models, dict):
            continue
        contexts = {}
        for model, item in models.items():
            limit = item.get("limit") if isinstance(item, dict) else None
            context = limit.get("context") if isinstance(limit, dict) else None
            if (isinstance(model, str) and isinstance(item, dict)
                    and item.get("id", model) == model
                    and type(context) is int and 0 < context <= 2_000_000):
                contexts[model] = context
        if contexts:
            result[provider] = contexts
    if not result:
        raise ValueError("No supported providers in public model catalog")
    return result


async def _download_catalog() -> dict[str, dict[str, int]]:
    # No channel URL, model ID or credential is sent to this public endpoint.
    async with (
        asyncio.timeout(20),
        httpx.AsyncClient(timeout=10, follow_redirects=False) as client,
        client.stream("GET", _CATALOG_URL, headers={"accept": "application/json"}) as response,
    ):
        response.raise_for_status()
        content = bytearray()
        async for chunk in response.aiter_bytes():
            if len(content) + len(chunk) > _MAX_BYTES:
                raise ValueError("Public model catalog is too large")
            content.extend(chunk)
    return _parse_catalog(json.loads(content))


class _CatalogCache:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._catalog: dict[str, dict[str, int]] = {}
        self._next_refresh = 0.0

    async def get(self) -> dict[str, dict[str, int]]:
        if monotonic() < self._next_refresh:
            return self._catalog
        async with self._lock:
            if monotonic() < self._next_refresh:
                return self._catalog
            try:
                catalog = await _download_catalog()
            except (httpx.HTTPError, TimeoutError, ValueError, UnicodeError) as exc:
                # A fallback outage must never invalidate successful upstream
                # discovery or discard the last good in-process catalog.
                logger.warning("Public model metadata refresh failed: %s", type(exc).__name__)
                self._next_refresh = monotonic() + _RETRY
            else:
                self._catalog = catalog
                self._next_refresh = monotonic() + _TTL
            return self._catalog


_cache = _CatalogCache()


async def fill_missing_contexts(kind: str, base: str, models: dict[str, int | None]) -> None:
    provider = _provider(kind, base)
    missing = [model for model, limit in models.items() if limit is None]
    if not provider or not missing:
        return
    catalog = await _cache.get()
    contexts = catalog.get(provider, {})
    for model in missing:
        if model in contexts:
            models[model] = contexts[model]
