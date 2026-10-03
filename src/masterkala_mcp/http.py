"""Shared async HTTP client for masterkala.com.

Every tool goes through `api` (JSON routes), `product_list` (HTML card fragment) or
`get_page` (server-rendered HTML). `_send` caps concurrency, retries once when the server
drops the connection, and turns HTTP failures into `ToolError` messages the model can act on.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

BASE = "https://masterkala.com"
API = f"{BASE}/api/2.1.1.0.0/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0",
}

MAX_CONCURRENCY = 4

_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None
_limit: asyncio.Semaphore | None = None


class ApiError(ToolError):
    """A failed upstream call."""


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport (tests use httpx.MockTransport). Drops the current client."""
    global _transport, _client, _limit
    _transport, _client, _limit = transport, None, None


def _get_client() -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
    global _client, _limit
    if _client is None:
        # MasterKala answers direct connections fastest; a system proxy is only used
        # when the user opts in with MASTERKALA_MCP_PROXY.
        _client = httpx.AsyncClient(
            transport=_transport,
            headers=HEADERS,
            timeout=30,
            follow_redirects=True,
            trust_env=False,
            proxy=os.environ.get("MASTERKALA_MCP_PROXY") or None,
        )
        _limit = asyncio.Semaphore(MAX_CONCURRENCY)
    assert _limit is not None
    return _client, _limit


async def api(route: str, body: dict[str, Any]) -> Any:
    """POST a JSON API route (`product/searchproduct`, ...) as a guest and return the parsed body."""
    # The site sends the JSON as text/plain with an empty Authorization header for guests.
    r = await _send("POST", API, params={"route": route}, content=json.dumps(body), headers={"Authorization": ""})
    try:
        data = r.json()
    except ValueError as e:
        raise ApiError(f"masterkala.com returned a non-JSON response for {route} (HTTP {r.status_code}).") from e
    if data is None:
        raise ApiError(f"masterkala.com returned no data for {route}. Check the id.")
    if isinstance(data, dict) and data.get("success") == "0":
        raise ApiError(f"masterkala.com rejected the request: {str(data.get('message') or data)[:300]}")
    return data


async def product_list(body: dict[str, Any]) -> str:
    """POST /fetch_content/product_list and return the HTML card fragment."""
    return (await _send("POST", f"{BASE}/fetch_content/product_list", json=body)).text


async def get_page(path: str) -> tuple[str, str]:
    """GET a site page; returns (final URL after redirects, HTML)."""
    r = await _send("GET", f"{BASE}{path}")
    return str(r.url), r.text


async def _send(method: str, url: str, **kwargs: Any) -> httpx.Response:
    client, limit = _get_client()
    for attempt in (1, 2):
        try:
            async with limit:
                r = await client.request(method, url, **kwargs)
            break
        except httpx.TimeoutException as e:
            raise ApiError("masterkala.com did not answer in time. Try again in a moment.") from e
        except httpx.TransportError as e:
            # The server drops about 1 in 80 TLS connections; a second try works.
            if attempt == 2:
                raise ApiError(
                    f"Could not reach masterkala.com ({type(e).__name__}). Check the internet connection, "
                    "or set MASTERKALA_MCP_PROXY."
                ) from e
    if r.status_code >= 400:
        raise ApiError(_status_message(r.status_code))
    return r


def _status_message(code: int) -> str:
    if code == 403:
        return "masterkala.com blocked the request (HTTP 403). Turn off VPN/proxy or set MASTERKALA_MCP_PROXY."
    if code == 404:
        return "Not found on masterkala.com (HTTP 404). Check the product id, category id, brand slug or tag id."
    if code == 429:
        return "masterkala.com is rate limiting requests (HTTP 429). Wait a minute before retrying."
    if code >= 500:
        return f"masterkala.com had a server error (HTTP {code}). Try again later."
    return f"masterkala.com rejected the request (HTTP {code})."
