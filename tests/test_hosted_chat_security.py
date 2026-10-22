"""Bounded model transport and public-endpoint pinning regressions."""

from __future__ import annotations

import socket
from contextlib import asynccontextmanager

import httpx
import pytest

from local_shell_mcp import hosted_chat
from local_shell_mcp.settings import get_settings


@pytest.fixture(autouse=True)
def settings(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.delenv("LOCAL_SHELL_MCP_HOSTED_CHAT_ALLOW_PRIVATE_ENDPOINTS", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def fake_dns(addresses):
    return [
        (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
        for ip in addresses
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["10.42.0.1"],
        ["169.254.169.254"],
        ["2001:db8::1"],
        ["93.184.216.34", "192.168.1.2"],
    ],
)
async def test_model_dns_rejects_any_non_global_address(monkeypatch, addresses):
    monkeypatch.setattr(hosted_chat.socket, "getaddrinfo", lambda *_a, **_k: fake_dns(addresses))
    with pytest.raises(ValueError, match="non-public"):
        await hosted_chat.model_request_target("https://gateway.example.com/v1")


@pytest.mark.asyncio
async def test_model_dns_pins_public_destination_and_preserves_sni(monkeypatch):
    monkeypatch.setattr(
        hosted_chat.socket, "getaddrinfo", lambda *_a, **_k: fake_dns(["93.184.216.34"])
    )
    url, headers, extensions = await hosted_chat.model_request_target(
        "https://gateway.example.com:8443/v1"
    )
    assert url == "https://93.184.216.34:8443/v1/chat/completions"
    assert headers == {"Host": "gateway.example.com:8443"}
    assert extensions == {"sni_hostname": "gateway.example.com"}
    monkeypatch.setattr(
        hosted_chat.socket, "getaddrinfo", lambda *_a, **_k: fake_dns(["2606:4700:4700::1111"])
    )
    url, _, _ = await hosted_chat.model_request_target("https://gateway.example.com/v1")
    assert url.startswith("https://[2606:4700:4700::1111]:443/")


@pytest.mark.asyncio
async def test_private_gateway_requires_admin_opt_in(monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_HOSTED_CHAT_ALLOW_PRIVATE_ENDPOINTS", "true")
    get_settings.cache_clear()
    assert await hosted_chat.model_request_target("http://127.0.0.1:8000/v1") == (
        "http://127.0.0.1:8000/v1/chat/completions",
        {},
        {},
    )


@pytest.mark.asyncio
async def test_model_body_stream_stops_at_limit(monkeypatch):
    monkeypatch.setattr(hosted_chat, "MAX_MODEL_RESPONSE_BYTES", 1024)
    seen = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(50):
                seen.append(1)
                yield b"x" * 256

    async def handler(_request):
        return httpx.Response(200, stream=Stream())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="size limit"):
            await hosted_chat.model_response_json(client, "https://test.example/v1", {}, {}, {})
    assert len(seen) < 50


@pytest.mark.asyncio
async def test_model_body_errors_and_valid_json():
    class JsonStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"choices":[{"message":{"content":"ok"}}]}'

    async def success(_request):
        return httpx.Response(200, stream=JsonStream())

    async with httpx.AsyncClient(transport=httpx.MockTransport(success)) as client:
        result = await hosted_chat.model_response_json(
            client, "https://test.example/v1", {}, {}, {}
        )
        assert result["choices"][0]["message"]["content"] == "ok"

    async def forbidden(_request):
        return httpx.Response(401, content=b"secret error body")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        with pytest.raises(ValueError, match="HTTP 401") as caught:
            await hosted_chat.model_response_json(client, "https://test.example/v1", {}, {}, {})
        assert "secret error body" not in str(caught.value)


@pytest.mark.asyncio
async def test_optional_api_key_does_not_send_bearer(monkeypatch):
    headers_seen = []

    @asynccontextmanager
    async def mcp(*_):
        yield object()

    async def model_target(endpoint):
        return endpoint + "/chat/completions", {}, {}

    async def model_response(_http, _url, headers, _extensions, _payload):
        headers_seen.append(headers)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(hosted_chat, "mcp_session", mcp)
    monkeypatch.setattr(hosted_chat, "model_request_target", model_target)
    monkeypatch.setattr(hosted_chat, "model_response_json", model_response)
    for key in ("", "token"):
        await hosted_chat.complete_turn(
            base_url="http://controller",
            bearer="",
            endpoint="https://example.org/v1",
            key=key,
            model="test",
            messages=[{"role": "user", "content": "hi"}],
            tools_enabled=False,
        )
    assert "Authorization" not in headers_seen[0]
    assert headers_seen[1]["Authorization"] == "Bearer token"


@pytest.mark.asyncio
async def test_endpoint_dns_lookup_failures_are_rejected(monkeypatch):
    def dns_failure(*_args, **_kwargs):
        raise socket.gaierror("lookup failed")

    monkeypatch.setattr(hosted_chat.socket, "getaddrinfo", dns_failure)
    with pytest.raises(ValueError, match="DNS lookup failed"):
        await hosted_chat.model_request_target("https://gateway.example.com/v1")
    monkeypatch.setattr(hosted_chat.socket, "getaddrinfo", lambda *_a, **_k: [])
    with pytest.raises(ValueError, match="no addresses"):
        await hosted_chat.model_request_target("https://gateway.example.com/v1")


@pytest.mark.asyncio
async def test_rejects_compressed_model_response():
    async def compressed(_request):
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=JsonStream())

    class JsonStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{}"

    async with httpx.AsyncClient(transport=httpx.MockTransport(compressed)) as client:
        with pytest.raises(ValueError, match="Compressed"):
            await hosted_chat.model_response_json(client, "https://test.example/v1", {}, {}, {})
