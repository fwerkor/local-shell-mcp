"""Optional BYOK chat host. All tool execution goes through the authenticated MCP endpoint."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MAX_MESSAGES = 64
MAX_STEPS = 8
MAX_CALLS = 24
MAX_TEXT = 40_000
MAX_MODEL_RESPONSE_BYTES = 4 * 1024 * 1024


def validate_endpoint(endpoint: str) -> str:
    from .settings import get_settings

    url = urlsplit(endpoint.strip())
    allow_private = get_settings().hosted_chat_allow_private_endpoints
    if (
        (url.scheme != "https" and not (allow_private and url.scheme == "http"))
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError(
            "Hosted Chat requires an HTTPS API base URL without credentials or query parameters"
        )
    host = url.hostname.lower()
    if not allow_private and (
        host == "localhost" or host.endswith((".localhost", ".local", ".internal"))
    ):
        raise ValueError(
            "Local/private model endpoints require a separately configured trusted gateway"
        )
    try:
        ip_address(host)
    except ValueError:
        pass
    else:
        if not allow_private:
            raise ValueError("Use a DNS name for the model API endpoint")
    return endpoint.strip().rstrip("/")


async def model_request_target(endpoint: str) -> tuple[str, dict[str, str], dict]:
    """Resolve and pin the HTTPS peer, without a second unvalidated DNS lookup.

    Host and SNI remain the original hostname for certificate verification.
    Disabling environment proxies prevents bypassing the pinned peer.
    """
    from .settings import get_settings

    original = urlsplit(endpoint)
    if get_settings().hosted_chat_allow_private_endpoints:
        return endpoint + "/chat/completions", {}, {}
    hostname = original.hostname or ""
    port = original.port or 443
    try:
        addresses = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, hostname, port, type=socket.SOCK_STREAM),
            timeout=15,
        )
    except socket.gaierror as exc:
        raise ValueError("Model endpoint DNS lookup failed") from exc
    if not addresses:
        raise ValueError("Model endpoint DNS lookup returned no addresses")
    resolved = [ip_address(item[4][0]) for item in addresses]
    if any(not address.is_global for address in resolved):
        raise ValueError("Model endpoint resolves to a non-public address")
    # Connecting to the checked literal address, not the DNS name, prevents
    # rebinding between the safety check and the actual TCP connection.
    selected = resolved[0]
    peer = f"[{selected}]" if selected.version == 6 else str(selected)
    host_header = hostname if port == 443 else f"{hostname}:{port}"
    target = original._replace(netloc=f"{peer}:{port}").geturl() + "/chat/completions"
    return target, {"Host": host_header}, {"sni_hostname": hostname}


async def model_response_json(
    http: httpx.AsyncClient, url: str, headers: dict, extensions: dict, payload: dict
) -> dict:
    async with http.stream(
        "POST", url, headers=headers, extensions=extensions, json=payload
    ) as response:
        if response.status_code >= 400:
            raise ValueError(f"Model API returned HTTP {response.status_code}")
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise ValueError("Compressed model responses are not supported")
        chunks = bytearray()
        async for chunk in response.aiter_raw(chunk_size=min(65536, MAX_MODEL_RESPONSE_BYTES)):
            if len(chunks) + len(chunk) > MAX_MODEL_RESPONSE_BYTES:
                raise ValueError("Model API response exceeds the size limit")
            chunks.extend(chunk)
        return json.loads(chunks)


def normalize_messages(messages: object) -> list[dict]:
    if not isinstance(messages, list):
        raise ValueError("Invalid or excessive chat history")
    cleaned = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {
            "system",
            "user",
            "assistant",
            "tool",
        }:
            raise ValueError("Invalid chat role")
        if message["role"] == "system":
            raise ValueError("Client-provided system messages are not supported")
        content = message.get("content")
        if content is not None and (not isinstance(content, str) or len(content) > MAX_TEXT):
            raise ValueError("Invalid message content")
        cleaned.append(
            {
                key: message[key]
                for key in ("role", "content", "tool_calls", "tool_call_id")
                if key in message
            }
        )
    return cleaned


@asynccontextmanager
async def mcp_session(base_url: str, bearer: str):
    headers = {"Authorization": bearer} if bearer else {}
    async with (
        httpx.AsyncClient(headers=headers, timeout=120, follow_redirects=False) as http,
        streamable_http_client(base_url.rstrip("/") + "/mcp", http_client=http) as (
            reader,
            writer,
            _,
        ),
        ClientSession(reader, writer) as session,
    ):
        await session.initialize()
        yield session


def tool_schema(tool: object) -> dict:
    data = tool.model_dump(by_alias=True, exclude_none=True)
    return {
        "type": "function",
        "function": {
            "name": data["name"],
            "description": data.get("description", ""),
            "parameters": data["inputSchema"],
        },
    }


def visible_tools(tools: object) -> list:
    return [
        t
        for t in tools
        if "app"
        not in ((t.model_dump(by_alias=True).get("_meta") or {}).get("ui") or {}).get(
            "visibility", []
        )
    ]


def safe_tool_message(result: object) -> str:
    data = result.model_dump(by_alias=True, exclude_none=True)
    # Never forward app tokens or host-only metadata to the model.
    data.pop("_meta", None)
    return json.dumps(data, ensure_ascii=False)[:MAX_TEXT]


async def call_mcp(base_url: str, bearer: str, name: str, arguments: dict) -> dict:
    async with mcp_session(base_url, bearer) as session:
        result = await session.call_tool(
            name, arguments, read_timeout_seconds=timedelta(seconds=120)
        )
        return result.model_dump(by_alias=True, exclude_none=True)


async def read_mcp_resource(base_url: str, bearer: str, uri: str) -> dict:
    if not uri.startswith("ui://"):
        raise ValueError("Only MCP App UI resources may be rendered")
    async with mcp_session(base_url, bearer) as session:
        result = await session.read_resource(uri)
        return result.model_dump(by_alias=True, exclude_none=True)


async def complete_turn(
    *,
    base_url: str,
    bearer: str,
    endpoint: str,
    key: str,
    model: str,
    messages: object,
    tools_enabled: bool,
    session_id: str | None = None,
    checkpoint: Callable[[list[dict], list[dict]], Awaitable[None]] | None = None,
) -> dict:
    endpoint = validate_endpoint(endpoint)
    if len(key) > 8_192 or not 0 < len(model) <= 256:
        raise ValueError("A model is required and API key must be at most 8192 characters")
    all_messages = normalize_messages(messages)
    # Full history stays on the server. Bound only the model request context.
    index = max(0, len(all_messages) - MAX_MESSAGES)
    while index > 0 and index < len(all_messages) and all_messages[index]["role"] != "user":
        index += 1
    history = all_messages[index:]
    if not history or history[-1]["role"] != "user":
        raise ValueError("A new user message is required")
    prompt = (
        "You are a technical assistant. When tools are enabled, use LSM tools to "
        "inspect and execute tasks. Follow tool schemas and permissions. "
        "Never place secrets in tool arguments or chat output. "
        "An LSM Logical Session is not the same thing as chat history."
    )
    if session_id:
        prompt += f" The user has explicitly attached LSM session_id={session_id!r}; pass it as logical_session_id to LSM tools."
    request_messages = [{"role": "system", "content": prompt}, *history]
    schemas = []
    known_tools: set[str] = set()
    events: list[dict] = []
    calls = 0

    async def save() -> None:
        if checkpoint is not None:
            await checkpoint([*all_messages[:index], *request_messages[1:]], events)

    async with mcp_session(base_url, bearer) as session:
        if tools_enabled:
            listed = visible_tools((await session.list_tools()).tools)
            schemas = [tool_schema(tool) for tool in listed]
            known_tools = {s["function"]["name"] for s in schemas}
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120, connect=15), follow_redirects=False, trust_env=False
        ) as model_http:
            for _step in range(MAX_STEPS):
                payload = {"model": model, "messages": request_messages, "stream": False}
                if schemas:
                    payload["tools"] = schemas
                    payload["tool_choice"] = "auto"
                url, host_headers, extensions = await model_request_target(endpoint)
                headers = {
                    "Content-Type": "application/json",
                    "Accept-Encoding": "identity",
                    **host_headers,
                }
                if key:
                    headers["Authorization"] = "Bearer " + key
                result = await model_response_json(model_http, url, headers, extensions, payload)
                answer = result["choices"][0]["message"]
                content = answer.get("content") or ""
                requested = answer.get("tool_calls") or []
                if not requested:
                    request_messages.append({"role": "assistant", "content": content})
                    await save()
                    return {"messages": request_messages[1:], "events": events}
                if not schemas or not isinstance(requested, list) or len(requested) > 8:
                    raise ValueError("Invalid model tool calls")
                assistant = {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": requested,
                }
                request_messages.append(assistant)
                await save()
                for tool_call in requested:
                    calls += 1
                    if calls > MAX_CALLS:
                        raise ValueError("Agent tool call limit reached")
                    name = tool_call.get("function", {}).get("name")
                    if name not in known_tools:
                        raise ValueError("Model requested an unknown or unauthorized tool")
                    try:
                        arguments = json.loads(tool_call["function"].get("arguments") or "{}")
                    except (ValueError, TypeError) as exc:
                        raise ValueError("Model produced invalid tool arguments") from exc
                    if not isinstance(arguments, dict):
                        raise ValueError("Tool arguments must be a JSON object")
                    if name not in {
                        "session_manage",
                        "plan_manage",
                        "workspace_open",
                        "open_live_workspace",
                    }:
                        arguments.setdefault("logical_session_id", session_id)
                    result = await session.call_tool(
                        name, arguments, read_timeout_seconds=timedelta(seconds=120)
                    )
                    event_record = result.model_dump(by_alias=True, exclude_none=True)
                    event_record.pop("_meta", None)
                    events.append(
                        {
                            "type": "tool",
                            "name": name,
                            "error": bool(result.isError),
                            "call_id": tool_call["id"],
                            "result": event_record,
                        }
                    )
                    request_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": safe_tool_message(result),
                        }
                    )
                    await save()
    raise ValueError("Agent iteration limit reached; inspect tool activity before continuing")
