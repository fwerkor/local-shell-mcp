"""Native Anthropic/Gemini tool protocols around the shared Agent tool loop.

No provider SDK is imported at startup. Provider continuation metadata stays in
server-side checkpoints, including Gemini function-call thought signatures.
"""
from __future__ import annotations

import json
import secrets
from collections.abc import AsyncIterator

from .providers import ModelToolCall, ProviderConfig, _data_frames


def native_messages(messages: list[dict], provider: str) -> tuple[list[dict], str]:
    result = []
    systems = []
    names = {}
    for message in messages:
        role = message.get("role")
        text = str(message.get("content") or "")
        if role == "system":
            systems.append(text)
            continue
        if role not in {"user", "assistant", "tool"}:
            continue
        parts = []
        if role == "tool":
            identity = message.get("tool_call_id")
            if provider == "anthropic":
                parts = [{"type": "tool_result", "tool_use_id": identity, "content": text}]
            else:
                function = {"name": names[identity], "response": {"result": text}}
                parts = [{"functionResponse": function}]
            native_role = "user"
        else:
            native_role = "model" if role == "assistant" and provider == "google" else role
            if text:
                parts.append({"type": "text", "text": text} if provider == "anthropic" else {"text": text})
            for call in message.get("tool_calls") or []:
                function = call["function"]
                names[call["id"]] = function["name"]
                arguments = json.loads(function["arguments"])
                if provider == "anthropic":
                    parts.append({"type": "tool_use", "id": call["id"], "name": function["name"], "input": arguments})
                else:
                    part = {"functionCall": {"name": function["name"], "args": arguments}}
                    metadata = call.get("provider_data") or {}
                    if metadata.get("thoughtSignature"):
                        part["thoughtSignature"] = metadata["thoughtSignature"]
                    parts.append(part)
        key = "content" if provider == "anthropic" else "parts"
        if parts:
            if result and result[-1]["role"] == native_role:
                result[-1][key].extend(parts)
            else:
                result.append({"role": native_role, key: parts})
    return result, "\n".join(systems)


async def stream_native_tools(config: ProviderConfig, messages: list[dict], *, tools: list[dict],
                              max_tokens: int, temperature: float | None,
                              top_p: float | None = None) -> AsyncIterator[str | ModelToolCall]:
    import httpx

    history, instructions = native_messages(messages, config.provider)
    headers = {"accept": "text/event-stream", "content-type": "application/json"}
    if config.provider == "anthropic":
        headers.update({"x-api-key": config.token, "anthropic-version": "2023-06-01"})
        body = {"model": config.model, "stream": True, "messages": history, "max_tokens": max_tokens,
                "tools": [{"name": t["function"]["name"], "description": t["function"].get("description", ""),
                           "input_schema": t["function"]["parameters"]} for t in tools]}
        if instructions:
            body["system"] = instructions
        if temperature is not None:
            body["temperature"] = temperature
        if top_p is not None:
            body["top_p"] = top_p
    else:
        headers["x-goog-api-key"] = config.token
        body = {"contents": history, "generationConfig": {"maxOutputTokens": max_tokens},
                "tools": [{"functionDeclarations": [
                    {"name": t["function"]["name"], "description": t["function"].get("description", ""),
                     "parametersJsonSchema": t["function"]["parameters"]} for t in tools]}]}
        if instructions:
            body["systemInstruction"] = {"parts": [{"text": instructions}]}
        if temperature is not None:
            body["generationConfig"]["temperature"] = temperature
        if top_p is not None:
            body["generationConfig"]["topP"] = top_p
    pending = {}
    timeout = httpx.Timeout(connect=20, read=config.timeout_s, write=30, pool=10)
    async with httpx.AsyncClient(timeout=timeout) as client, client.stream(
        "POST", config.url, headers=headers, json=body,
    ) as response:
        response.raise_for_status()
        async for frame in _data_frames(response):
            if frame == "[DONE]":
                break
            try:
                event = json.loads(frame)
            except json.JSONDecodeError:
                continue
            if "error" in event:
                raise RuntimeError("Model provider rejected the generation request")
            if config.provider == "anthropic":
                kind = event.get("type")
                index = event.get("index")
                if kind == "content_block_start" and event.get("content_block", {}).get("type") == "tool_use":
                    if type(index) is not int or not 0 <= index < 8 or len(pending) >= 4:
                        raise ValueError("Invalid model tool call index")
                    block = event["content_block"]
                    pending[index] = {"id": block.get("id"), "name": block.get("name"),
                                      "arguments": "", "initial": block.get("input", {})}
                elif kind == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                        yield delta["text"]
                    elif delta.get("type") == "input_json_delta":
                        if index not in pending:
                            raise ValueError("Tool arguments arrived before tool declaration")
                        pending[index]["arguments"] += str(delta.get("partial_json") or "")
                        if len(pending[index]["arguments"]) > 8192:
                            raise ValueError("Model tool call exceeds allowed size")
            else:
                for candidate in event.get("candidates", [])[:1]:
                    for part in (candidate.get("content") or {}).get("parts", []):
                        if isinstance(part.get("text"), str) and not part.get("thought"):
                            yield part["text"]
                        function = part.get("functionCall")
                        if function is not None:
                            if len(pending) >= 4 or not isinstance(function, dict):
                                raise ValueError("Invalid model tool call")
                            pending[len(pending)] = {"id": "call_" + secrets.token_hex(12),
                                "name": function.get("name"), "initial": function.get("args", {}),
                                "arguments": "", "metadata": {"thoughtSignature": part.get("thoughtSignature")}}
    for item in pending.values():
        arguments = json.loads(item["arguments"]) if item["arguments"] else item["initial"]
        if (not isinstance(arguments, dict) or len(json.dumps(arguments)) > 8192 or
            not isinstance(item["name"], str) or not 1 <= len(item["name"]) <= 128 or
            not isinstance(item["id"], str) or not 1 <= len(item["id"]) <= 128):
            raise ValueError("Invalid model tool call")
        yield ModelToolCall(item["id"], item["name"], arguments, item.get("metadata"))
