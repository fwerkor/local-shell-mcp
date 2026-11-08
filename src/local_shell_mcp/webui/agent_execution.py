"""Direct tool-batch execution ported from agents 4.0.1 ToolNode.ts.

The source waits for every sibling, restores immutable completed proposals on
replay and runs interrupt-capable tools before ordinary side-effecting siblings.
Model routing/checkpoint channels are handled by the caller.
"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Awaitable, Callable, MutableMapping, Sequence
from typing import Any

from .providers import ModelToolCall


def replay_key(call: ModelToolCall, position: int) -> str:
    return json.dumps(["id", call.call_id] if call.call_id else ["position", position],
                      separators=(",", ":"))


def _same_args(left: Any, right: Any) -> bool:
    # JSON.stringify emits integral floats as integers and distinguishes
    # booleans from numbers; Python's ordinary equality does the opposite.
    def normalized(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: normalized(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalized(item) for item in value]
        if type(value) is float and value.is_integer():
            return int(value)
        return value

    return json.dumps(normalized(left), sort_keys=True, ensure_ascii=False, allow_nan=False) == json.dumps(
        normalized(right), sort_keys=True, ensure_ascii=False, allow_nan=False,
    )


async def execute_tool_batch(
    calls: Sequence[ModelToolCall],
    execute: Callable[[ModelToolCall], Awaitable[Any]],
    *,
    settled: MutableMapping[str, dict] | None = None,
    interrupting_names: frozenset[str] = frozenset(),
    is_interrupt: Callable[[BaseException], bool] = lambda error: False,
    check_breaker: Callable[[], None] = lambda: None,
    on_completed: Callable[[ModelToolCall, dict], Awaitable[None]] | None = None,
) -> list[Any]:
    cache = settled if settled is not None else {}

    async def run_one(position: int) -> Any:
        call = calls[position]
        key = replay_key(call, position)
        cached = cache.get(key)
        if cached is not None:
            proposal = cached["proposal"]
            if proposal["name"] != call.name or not _same_args(proposal["args"], call.arguments):
                raise ValueError("Cannot change an already completed tool call during approval replay")
            return copy.deepcopy(cached["output"])
        output = await execute(call)
        result = {"proposal": copy.deepcopy({"name": call.name, "args": call.arguments}),
                  "output": copy.deepcopy(output)}
        if on_completed is not None:
            await on_completed(call, result)
        cache[key] = result
        return output

    async def settle(positions: list[int], *, prefer_non_interrupt: bool) -> list[Any]:
        results = await asyncio.gather(*(run_one(position) for position in positions),
                                       return_exceptions=True)
        check_breaker()
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            failure = next((error for error in failures if not is_interrupt(error)), failures[0]) \
                if prefer_non_interrupt else failures[0]
            raise failure
        return results

    check_breaker()
    interrupting = [i for i, call in enumerate(calls) if call.name in interrupting_names]
    if not interrupting:
        return await settle(list(range(len(calls))), prefer_non_interrupt=True)
    ordinary = [i for i, call in enumerate(calls) if call.name not in interrupting_names]
    outputs: list[Any] = [None] * len(calls)
    first = await settle(interrupting, prefer_non_interrupt=False)
    for position, output in zip(interrupting, first, strict=True):
        outputs[position] = output
    check_breaker()
    rest = await settle(ordinary, prefer_non_interrupt=True)
    for position, output in zip(ordinary, rest, strict=True):
        outputs[position] = output
    return outputs
