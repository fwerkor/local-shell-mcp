"""Stateless OpenAI Responses transport for the existing LSM model harness."""
from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from .approval_runtime import truncate_approval_result
from .mcp_projection import HARD_MAX_TOOL_RESULT_CHARS, project_artifact_messages
from .providers import (
    ModelFinish,
    ModelThought,
    ModelToolCall,
    ModelUsage,
    ProviderConfig,
    UnsupportedImageInput,
    _data_frames,
    _usage_frame,
    check_image_response,
    image_input_rejected,
)

PROTOCOL = "openai-responses"
_MAX_ARGUMENTS = 1024 * 1024


# Only recognized machine-readable codes are exposed. Upstream free-form
# messages may contain request data, URLs or credentials.
_TRANSIENT_ERROR_CODES = frozenset({
    "server_error", "internal_server_error", "rate_limit_exceeded",
    "rate_limit_error", "overloaded_error", "overloaded", "service_unavailable",
    "temporarily_unavailable", "timeout", "request_timeout", "gateway_timeout",
    "engine_overloaded", "model_overloaded", "internal_error",
    "cancelled", "canceled",
})
_PERMANENT_ERROR_CODES = frozenset({
    "invalid_request_error", "invalid_request", "invalid_api_key",
    "authentication_error", "permission_denied", "insufficient_quota",
    "quota_exceeded", "billing_hard_limit_reached", "model_not_found",
    "context_length_exceeded", "content_filter", "content_policy_violation",
    "invalid_prompt", "unsupported_value", "invalid_value",
    "missing_required_parameter", "invalid_parameter", "usage_limit_reached",
})


class ResponsesStreamError(RuntimeError):
    """A provider-side SSE failure, with safe diagnostics and retry classification."""

    def __init__(self, event_type: str, code: str | None = None):
        self.event_type = event_type
        self.code = code if code in _TRANSIENT_ERROR_CODES | _PERMANENT_ERROR_CODES else (
            "unrecognized_code" if code else None)
        # Some providers send bare failed/cancelled events without an error
        # object. Give these a bounded retry too, but never guess that an
        # explicit unknown or permanent code is temporary.
        self.retryable = code in _TRANSIENT_ERROR_CODES or (
            code is None and event_type in {
                "error", "response.failed", "response.cancelled", "stream_disconnected"
            })
        detail = f"; code={self.code}" if self.code else "; no error code supplied"
        super().__init__(f"Responses provider generation failed ({event_type}{detail})")

    @classmethod
    def from_event(cls, event: dict, *, event_type: str | None = None):
        response = event.get("response")
        nested_error = response.get("error") if isinstance(response, dict) else None
        top_error = event.get("error")
        code = None
        for source in (nested_error, top_error, event):
            if isinstance(source, dict):
                value = source.get("code")
                if isinstance(value, str) and value:
                    code = value
                    break
        if code is None:
            for source in (nested_error, top_error):
                if isinstance(source, dict):
                    value = source.get("type")
                    if isinstance(value, str) and value:
                        code = value
                        break
        return cls(event_type or event["type"], code)


def _scope(config: ProviderConfig) -> str:
    # Never replay opaque provider state to another endpoint, account or model.
    return hashlib.sha256(json.dumps([config.url, config.model, config.account_id or config.token]).encode()).hexdigest()


def _parts(content, *, assistant=False) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "output_text" if assistant else "input_text", "text": content}] if content else []
    if content is None:
        return []
    if not isinstance(content, list):
        raise ValueError("Invalid Responses message content")
    result = []
    for part in content:
        if not isinstance(part, dict):
            raise ValueError("Invalid Responses content part")
        kind = part.get("type")
        if kind == "text" and isinstance(part.get("text"), str):
            result.extend(_parts(part["text"], assistant=assistant))
        elif not assistant and kind == "image_url":
            image = part.get("image_url")
            if not isinstance(image, dict) or not isinstance(image.get("url"), str):
                raise ValueError("Invalid Responses image")
            result.append({"type": "input_image", "image_url": image["url"],
                           "detail": image.get("detail", "auto")})
        elif not assistant and kind == "file":
            file = part.get("file")
            if not isinstance(file, dict):
                raise ValueError("Invalid Responses file")
            fields = {k: file[k] for k in ("file_id", "file_data", "filename") if isinstance(file.get(k), str)}
            if not fields.get("file_id") and not fields.get("file_data"):
                raise ValueError("Invalid Responses file")
            result.append({"type": "input_file", **fields})
        else:
            raise ValueError("Unsupported Responses content part")
    return result


def _text(item: dict) -> str:
    return "".join(part.get("text", "") if part.get("type") == "output_text" else
                   part.get("refusal", "") if part.get("type") == "refusal" else ""
                   for part in item.get("content") or [] if isinstance(part, dict))


def _call_item(call: dict) -> dict:
    fn = call["function"]
    arguments = fn["arguments"]
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments, ensure_ascii=False)
    return {"type": "function_call", "call_id": call["id"], "name": fn["name"], "arguments": arguments}


def _assistant_items(message: dict, scope: str) -> list[dict]:
    """Replay completed provider output order only if it still matches canonical history.

    Tool arguments always come from the canonical, permission-checked history.
    If text has been edited or compacted, omit stale native metadata.
    """
    content = _parts(message.get("content"), assistant=True)
    calls = message.get("tool_calls") or []
    fallback = ([{"role": "assistant", "content": "".join(part["text"] for part in content)}] if content else []) + [_call_item(c) for c in calls]
    metadata = [part for part in message.get("reasoning") or []
                if part.get("type") == "responses_item" and part.get("scope") == scope]
    if not metadata:
        return fallback
    items: dict[int, dict] = {}
    expected_calls: dict[int, str] = {}
    for part in metadata:
        index, item = part.get("index"), part.get("item")
        if type(index) is not int or index < 0 or index in items or not isinstance(item, dict):
            return fallback
        if item.get("type") == "function_call":
            if index in expected_calls or not isinstance(item.get("call_id"), str):
                return fallback
            expected_calls[index] = item["call_id"]
            continue
        if index in expected_calls:
            return fallback
        if item.get("type") == "reasoning":
            # Encrypted reasoning is opaque; preserve it only for the originating connection.
            if not item.get("encrypted_content"):
                continue
        elif item.get("type") != "message":
            return fallback
        items[index] = item
    original_text = "".join(_text(item) for _, item in sorted(items.items()) if item["type"] == "message")
    if original_text != "".join(part["text"] for part in content):
        return fallback
    for call in calls:
        data = call.get("provider_data") or {}
        index = data.get("responses_index")
        if (data.get("responses_scope") != scope or type(index) is not int or index < 0
                or index in items or expected_calls.pop(index, None) != call["id"]):
            return fallback
        items[index] = _call_item(call)
    # Do not replay a half-persisted or preempted tool batch.
    if expected_calls:
        return fallback
    return [item for _, item in sorted(items.items())]


def responses_input(config: ProviderConfig, messages: list[dict]) -> list[dict]:
    result = []
    scope = _scope(config)
    for message in project_artifact_messages(messages, PROTOCOL):
        role = message.get("role")
        if role == "assistant":
            result.extend(_assistant_items(message, scope))
        elif role == "tool":
            identity = message.get("tool_call_id")
            if not isinstance(identity, str) or not identity:
                raise ValueError("Responses tool result missing call ID")
            content = message.get("content", "")
            output = (truncate_approval_result(content, HARD_MAX_TOOL_RESULT_CHARS)
                      if isinstance(content, str) else _parts(content))
            result.append({"type": "function_call_output", "call_id": identity, "output": output})
        elif role in {"system", "developer", "user"}:
            content = _parts(message.get("content"))
            if content:
                result.append({"role": "developer" if role == "system" and config.auth_method == "chatgpt" else role, "content": content})
        else:
            raise ValueError("Unsupported Responses message role")
    if config.auth_method == "chatgpt":
        calls = {}
        for item in result:
            if item.get("type") == "function_call":
                item["namespace"] = "lsm"
                calls[item["call_id"]] = item["name"]
            elif item.get("type") == "function_call_output" and item.get("call_id") in calls:
                item["namespace"] = "lsm"
                item["name"] = calls[item["call_id"]]
    return result


def _tools(tools: list[dict]) -> list[dict]:
    result = []
    for tool in tools:
        if tool.get("type") != "function" or not isinstance(tool.get("function"), dict):
            raise ValueError("Unsupported Responses tool declaration")
        fn = tool["function"]
        result.append({"type": "function", "name": fn["name"],
                       **{key: fn[key] for key in ("description", "parameters") if key in fn},
                       # Chat Completions schemas are not necessarily strict-compatible.
                       "strict": fn.get("strict", False)})
    return result


def _metadata_item(item: dict) -> dict | None:
    """Keep only supported replay fields, never arbitrary provider extensions."""
    if item.get("type") == "reasoning" and isinstance(item.get("encrypted_content"), str):
        return {key: item[key] for key in ("type", "id", "summary", "encrypted_content", "status") if key in item}
    if item.get("type") == "message" and item.get("role") == "assistant":
        return {key: item[key] for key in ("type", "id", "role", "content", "phase", "status") if key in item}
    if item.get("type") == "function_call":
        # Record identity/order only: canonical tool calls own arguments.
        return {"type": "function_call", "call_id": item["call_id"]}
    return None



@asynccontextmanager
async def _response_stream(client, config, body, headers):
    """Resolve account credentials just before use; retry only a pre-stream 401."""
    if not config.account_id:
        async with client.stream("POST", config.url, json=body, headers=headers) as response:
            yield response
        return
    from .model_oauth import access_token, adapter
    from .routes import _repo
    if config.url != adapter(config.auth_method).base_url + "/responses":
        raise ValueError("Account authorization cannot be used at a different API endpoint")
    database = _repo().database
    token = await access_token(database, config.account_channel, config.account_id)
    for attempt in range(2):
        async with client.stream("POST", config.url, json=body,
                                 headers={**headers, "Authorization": "Bearer " + token}) as response:
            if response.status_code != 401 or attempt:
                yield response
                return
        token = await access_token(database, config.account_channel, config.account_id, rejected=token)

async def stream_responses(config: ProviderConfig, messages: list[dict], *, tools: list[dict],
                           max_tokens: int | None = None, temperature: float | None = None,
                           top_p: float | None = None, emit_finish_reason: bool = False
                           ) -> AsyncIterator[str | ModelThought | ModelToolCall | ModelUsage | ModelFinish]:
    import httpx

    scope = _scope(config)
    headers = {"accept": "text/event-stream", "content-type": "application/json"}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"
    body = {"model": config.model, "input": responses_input(config, messages),
            "stream": True, "store": False, "include": ["reasoning.encrypted_content"]}
    if tools:
        wire_tools = _tools(tools)
        if config.auth_method == "chatgpt":
            # Namespaces are required by ChatGPT plan usage; keep function names stable.
            wire_tools = [{"type": "namespace", "name": "lsm", "description": "Local tools", "tools": wire_tools}]
        body.update(tools=wire_tools, tool_choice="auto", parallel_tool_calls=True)
    for key, value in (("max_output_tokens", max_tokens), ("temperature", temperature), ("top_p", top_p)):
        if value is not None and config.auth_method != "chatgpt":
            body[key] = value
    timeout = httpx.Timeout(connect=20, read=config.timeout_s, write=30, pool=10)
    done: dict[int, dict] = {}
    seen_text: dict[int, str] = {}
    terminal = None
    async with (
        httpx.AsyncClient(timeout=timeout) as client,
        _response_stream(client, config, body, headers) as response,
    ):
        await check_image_response(response)
        async for frame in _data_frames(response):
            if frame == "[DONE]":
                break
            try:
                event = json.loads(frame)
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid Responses SSE frame") from exc
            if not isinstance(event, dict):
                raise ValueError("Invalid Responses SSE event")
            kind = event.get("type")
            if kind in {"error", "response.failed", "response.cancelled"}:
                if image_input_rejected(json.dumps(event)):
                    raise UnsupportedImageInput("Provider does not support image input")
                raise ResponsesStreamError.from_event(event)
            if kind in {"response.output_text.delta", "response.refusal.delta"}:
                delta, index = event.get("delta"), event.get("output_index")
                if not isinstance(delta, str) or type(index) is not int or index < 0:
                    raise ValueError("Invalid Responses text delta")
                seen_text[index] = seen_text.get(index, "") + delta
                if delta:
                    yield delta
            elif kind in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
                delta = event.get("delta")
                if isinstance(delta, str) and delta:
                    yield ModelThought("thinking", text=delta)
            elif kind == "response.output_item.done":
                index, item = event.get("output_index"), event.get("item")
                if type(index) is not int or index < 0 or not isinstance(item, dict):
                    raise ValueError("Invalid Responses output item")
                done[index] = item
            elif kind in {"response.completed", "response.incomplete"}:
                terminal = event
                break
    if terminal is None:
        # A dropped stream must never execute partially observed tool calls.
        raise ResponsesStreamError("stream_disconnected")
    response = terminal.get("response")
    if not isinstance(response, dict):
        raise ValueError("Responses terminal event missing response")
    incomplete = terminal["type"] == "response.incomplete" or response.get("status") == "incomplete"
    if response.get("status") in {"failed", "cancelled"}:
        raise ResponsesStreamError.from_event(terminal, event_type=f"response.{response['status']}")
    output = response.get("output")
    if isinstance(output, list):
        items = list(enumerate(output))
    elif output is None:
        items = sorted(done.items())
    else:
        raise ValueError("Invalid Responses output")
    if seen_text.keys() - {index for index, item in items if isinstance(item, dict) and item.get("type") == "message"}:
        raise ValueError("Responses terminal output is missing streamed text")
    calls = []
    replay = []
    identities = set()
    for index, item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid Responses output item")
        kind = item.get("type")
        if kind == "message":
            text = _text(item)
            streamed = seen_text.get(index, "")
            if not text.startswith(streamed):
                raise ValueError("Responses final text disagrees with streamed text")
            if len(text) > len(streamed):
                yield text[len(streamed):]
        elif kind == "function_call":
            if incomplete or item.get("status") not in {None, "completed"}:
                raise RuntimeError("Responses generation ended with an incomplete tool call")
            identity, name, args = item.get("call_id"), item.get("name"), item.get("arguments")
            if config.auth_method == "chatgpt" and item.get("namespace") not in {None, "lsm"}:
                raise ValueError("Invalid Responses function namespace")
            if not tools or not isinstance(identity, str) or not identity or identity in identities or not isinstance(name, str) or not name:
                raise ValueError("Invalid Responses function call")
            if not isinstance(args, str) or len(args) > _MAX_ARGUMENTS:
                raise ValueError("Invalid Responses function arguments")
            try:
                arguments = json.loads(args)
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid JSON in Responses function arguments") from exc
            if not isinstance(arguments, dict):
                raise ValueError("Responses function arguments must be an object")
            identities.add(identity)
            calls.append(ModelToolCall(identity, name, arguments,
                                       {"responses_index": index, "responses_scope": scope}))
        elif kind != "reasoning":
            raise ValueError("Unsupported Responses output item")
        native = _metadata_item(item)
        if native is not None and not incomplete:
            replay.append(ModelThought("responses_item", provider_data={"scope": scope, "index": index, "item": native}))
    # Usage is emitted even for incomplete text responses. No side-effecting
    # calls are released until the complete response is validated.
    usage = _usage_frame("openai", response)
    if usage is not None:
        yield ModelUsage(PROTOCOL, usage.input_tokens, usage.output_tokens,
                         usage.cache_read, usage.cache_write)
    if incomplete and not emit_finish_reason:
        raise RuntimeError("Responses generation was incomplete")
    for item in replay:
        yield item
    for call in calls:
        yield call
    if emit_finish_reason:
        details = response.get("incomplete_details") or {}
        yield ModelFinish(PROTOCOL, "max_output_tokens" if incomplete and details.get("reason") == "max_output_tokens" else "incomplete" if incomplete else "stop")
