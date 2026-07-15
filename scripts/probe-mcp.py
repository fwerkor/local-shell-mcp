#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


async def oauth_token(base_url: str, pin: str) -> str:
    redirect_uri = "https://example.com/local-shell-mcp-probe"
    verifier = secrets.token_urlsafe(48)
    async with httpx.AsyncClient(follow_redirects=False, timeout=20) as client:
        registered = await client.post(
            f"{base_url}/oauth/register",
            json={"redirect_uris": [redirect_uri], "client_name": "local-shell-mcp-probe"},
        )
        registered.raise_for_status()
        client_id = registered.json()["client_id"]

        authorized = await client.post(
            f"{base_url}/oauth/authorize",
            data={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": "shell:read shell:write shell:execute browser:use remote:use",
                "code_challenge": _pkce_challenge(verifier),
                "code_challenge_method": "S256",
                "pin": pin,
            },
        )
        if authorized.status_code not in {302, 303, 307, 308}:
            authorized.raise_for_status()
        code = parse_qs(urlparse(authorized.headers["location"]).query)["code"][0]

        token = await client.post(
            f"{base_url}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
        )
        token.raise_for_status()
        return token.json()["access_token"]


async def list_tools(mcp_url: str, token: str | None = None) -> list[str]:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with streamablehttp_client(
        mcp_url,
        headers=headers,
        timeout=20,
        sse_read_timeout=20,
    ) as (read, write, _), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        return [tool.name for tool in tools.tools]


async def call_environment_info(mcp_url: str, token: str) -> bool:
    async with streamablehttp_client(
        mcp_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
        sse_read_timeout=20,
    ) as (read, write, _), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("environment_info", {})
        return not bool(result.isError)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Probe a local-shell-mcp remote endpoint.")
    parser.add_argument("base_url", help="Public base URL, for example https://mcp.example.com")
    parser.add_argument("--pin", help="OAuth admin PIN. If set, also tests an authenticated tool call.")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    mcp_url = f"{base_url}/mcp"

    async with httpx.AsyncClient(timeout=20) as client:
        for path in ("/healthz", "/.well-known/oauth-protected-resource", "/.well-known/oauth-authorization-server"):
            response = await client.get(f"{base_url}{path}")
            print(f"{path}: {response.status_code}")
            response.raise_for_status()

    if args.pin:
        token = await oauth_token(base_url, args.pin)
        tools = await list_tools(mcp_url, token)
        print(f"authenticated initialize/list_tools: ok ({len(tools)} tools)")
        print("first tools:", ", ".join(tools[:8]))
        ok = await call_environment_info(mcp_url, token)
        print(f"authenticated environment_info call: {'ok' if ok else 'failed'}")
    else:
        tools = await list_tools(mcp_url)
        print(f"unauthenticated initialize/list_tools: ok ({len(tools)} tools)")
        print("first tools:", ", ".join(tools[:8]))


if __name__ == "__main__":
    asyncio.run(main())
