"""Shared async HTTP client for masterkala.com.

Every tool goes through `api` (JSON routes), `product_list` (HTML card fragment) or
`get_page` (server-rendered HTML). `_send` caps concurrency, retries transient failures,
passes a bot check through a real browser when one is installed, and turns HTTP failures
into `ToolError` messages the model can act on.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from httpx_curl_cffi import AsyncCurlTransport
from mcp.server.mcpserver.exceptions import ToolError

BASE = "https://masterkala.com"
API = f"{BASE}/api/2.1.1.0.0/"

HEADERS = {
    # User-Agent, sec-ch-ua and TLS come from the impersonated Chrome profile (see _get_client).
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
    "Origin": BASE,
    "Referer": f"{BASE}/",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "priority": "u=1, i",
}
# curl_cffi ignores a client-level Accept equal to the httpx default, so each call sets its own.
# get_page loads whole pages the way a link click does.
PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "priority": "u=0, i",
}

MAX_CONCURRENCY = 2
JITTER = (0.15, 0.6)  # seconds before each upstream call
MAX_RETRIES = 2
MAX_RETRY_WAIT = 10  # cap for Retry-After and backoff, seconds
RETRY_DELAY = 0.5

_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None
_limit: asyncio.Semaphore | None = None
_proxy_index = 0
_retired: set[asyncio.Task] = set()
_browser_lock: asyncio.Lock | None = None
_cleared: tuple[httpx.AsyncClient, float] | None = None
CACHE_TTL = 3600  # seconds, for near-static parsed lists (categories, brands)
_cache: dict[str, tuple[float, Any]] = {}


class _XhrTransport(AsyncCurlTransport):
    """The Chrome profile sends navigation-only headers; a None value makes curl drop them (API calls are XHR)."""

    def _create_request_params(self, req: httpx.Request) -> dict[str, Any]:
        p = super()._create_request_params(req)
        p["headers"] = [*p["headers"], (b"upgrade-insecure-requests", None), (b"sec-fetch-user", None)]
        return p


async def cached(key: str, build: Callable[[], Awaitable[Any]]) -> Any:
    """Return `build()` for `key`, reusing the result for CACHE_TTL seconds. Callers must not mutate it."""
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]
    value = await build()
    _cache[key] = (time.monotonic(), value)
    return value


def clip(text: str, n: int = 400, full: bool = False) -> str:
    """Cut untrusted site text to n characters, marking the cut. full=True keeps all of it."""
    return text if full or len(text) <= n else text[:n].rstrip() + "…[truncated]"


class ApiError(ToolError):
    """A failed upstream call. `status` is the HTTP status, or None for network errors."""

    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport (tests use httpx.MockTransport). Drops the current client."""
    global _transport, _client, _limit, _proxy_index, _browser_lock, _cleared
    _transport, _client, _limit, _proxy_index, _browser_lock, _cleared = transport, None, None, 0, None, None
    _cache.clear()


def _proxies() -> list[str]:
    """MASTERKALA_MCP_PROXY: one proxy URL, or a comma-separated list used one at a time."""
    return [p.strip() for p in os.environ.get("MASTERKALA_MCP_PROXY", "").split(",") if p.strip()]


_CHALLENGE = re.compile(r"just a moment|captcha|challenge|arvan|attention required|enable javascript", re.I)


def _is_challenge(r: httpx.Response) -> bool:
    """A bot-check page: 403/429/503 with an HTML body that carries a known challenge marker."""
    return (
        r.status_code in (403, 429, 503)
        and "html" in r.headers.get("content-type", "") + r.text[:20].lower()
        and bool(_CHALLENGE.search(r.text[:5000]))
    )


def _next_proxy(client: httpx.AsyncClient) -> None:
    """Sticky pool: move to the next proxy after a block or connect error; the next call rebuilds the client.

    Only the client that failed may rotate: a slower request that failed on an old client must not skip a good proxy.
    The old client is closed late because other requests may still be using it.
    """
    global _client, _limit, _proxy_index
    if len(_proxies()) < 2 or client is not _client:
        return
    _client, _limit, _proxy_index = None, None, _proxy_index + 1
    t = asyncio.create_task(_close_later(client))
    _retired.add(t)
    t.add_done_callback(_retired.discard)


async def _close_later(client: httpx.AsyncClient) -> None:
    await asyncio.sleep(40)  # longer than the 30 s request timeout
    await client.aclose()


def _get_client() -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
    global _client, _limit
    if _client is None:
        # MasterKala answers direct connections fastest; a system proxy is only used when the user opts in with
        # MASTERKALA_MCP_PROXY. curl_cffi presents Chrome's TLS/HTTP2 fingerprint and default headers; cookies and
        # redirects stay with httpx. The proxy goes to the transport (a client-level proxy is ignored once a
        # transport is given).
        proxies = _proxies()
        _client = httpx.AsyncClient(
            transport=_transport
            or _XhrTransport(
                impersonate="chrome",
                default_headers=True,
                proxy=proxies[_proxy_index % len(proxies)] if proxies else None,
                max_connections=2 * MAX_CONCURRENCY,
            ),
            headers=HEADERS,
            timeout=30,
            limits=httpx.Limits(max_connections=2 * MAX_CONCURRENCY),
            follow_redirects=True,
            trust_env=False,
        )
        _limit = asyncio.Semaphore(MAX_CONCURRENCY)
    assert _limit is not None
    return _client, _limit


async def api(route: str, body: dict[str, Any]) -> Any:
    """POST a JSON API route (`product/searchproduct`, ...) as a guest and return the parsed body."""
    # The site sends the JSON as text/plain with an empty Authorization header for guests.
    r = await _send(
        "POST",
        API,
        params={"route": route},
        content=json.dumps(body),
        headers={
            "Accept": "application/json, text/plain, */*",
            "Authorization": "",
            "Content-Type": "text/plain;charset=UTF-8",
        },
    )
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
    return (
        await _send("POST", f"{BASE}/fetch_content/product_list", json=body, headers={"Accept": "text/html, */*"})
    ).text


async def get_page(path: str) -> tuple[str, str]:
    """GET a site page; returns (final URL after redirects, HTML)."""
    r = await _send("GET", f"{BASE}{path}", headers=PAGE_HEADERS)
    return str(r.url), r.text


async def _send(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Send with jitter; retry a timeout, network error, 5xx or 429 up to MAX_RETRIES times. 403 is never retried."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await _send_once(method, url, **kwargs)
        except ApiError as e:
            if attempt == MAX_RETRIES or (e.status is not None and e.status < 500 and e.status != 429):
                raise
            wait = e.retry_after if e.retry_after is not None else RETRY_DELAY * 2**attempt * random.uniform(1, 1.5)
            await asyncio.sleep(min(wait, MAX_RETRY_WAIT))
    raise AssertionError("unreachable")


async def _request(client: httpx.AsyncClient, limit: asyncio.Semaphore, method: str, url: str, **kwargs: Any):
    try:
        async with limit:
            await asyncio.sleep(random.uniform(*JITTER))
            return await client.request(method, url, **kwargs)
    except httpx.TimeoutException as e:
        raise ApiError("masterkala.com did not answer in time. Try again in a moment.") from e
    except httpx.RequestError as e:
        # The server also drops about 1 in 80 TLS connections; the retry in _send covers it.
        if isinstance(e, httpx.ConnectError | httpx.ProxyError | httpx.TooManyRedirects):
            _next_proxy(client)
        raise ApiError(
            f"Could not reach masterkala.com ({type(e).__name__}). Check the internet connection, "
            "or set MASTERKALA_MCP_PROXY."
        ) from e


async def _send_once(method: str, url: str, **kwargs: Any) -> httpx.Response:
    client, limit = _get_client()
    r = await _request(client, limit, method, url, **kwargs)
    if _is_challenge(r):
        _next_proxy(client)
        client, limit = _get_client()
        await _clear_challenge(client)
        r = await _request(client, limit, method, url, **kwargs)  # one retry; a second block is final
        if _is_challenge(r):
            _next_proxy(client)
    if r.status_code >= 400:
        raise ApiError(_status_message(r.status_code), r.status_code, _retry_after(r))
    return r


async def _browser_cookies(proxy: str | None) -> list[dict[str, Any]]:
    """Open the home page in headless patchright, wait for the challenge to clear, return the cookies."""
    try:
        from patchright.async_api import async_playwright
    except ImportError as e:
        raise ApiError(
            "masterkala.com served a bot-check page. Install the browser extra (`pip install masterkala-mcp[browser]`, "
            "or `uvx --with patchright==1.63.0 masterkala-mcp`) and run `patchright install chromium`.",
            403,
        ) from e
    u = httpx.URL(proxy) if proxy else None
    opts = u and {"server": f"{u.scheme}://{u.host}:{u.port}", "username": u.username, "password": u.password}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, proxy=opts)
        try:
            page = await browser.new_page()
            await page.goto(BASE, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_function(
                "!/just a moment|access denied|attention required|arvancloud/i.test(document.title)", timeout=30_000
            )
            return await browser.contexts[0].cookies()
        finally:
            await browser.close()


async def _clear_challenge(client: httpx.AsyncClient) -> None:
    """Rung 2: let a real browser pass the bot check once and share its cookies with the httpx jar."""
    global _browser_lock, _cleared
    _browser_lock = _browser_lock or asyncio.Lock()
    async with _browser_lock:  # one browser at a time; callers that waited reuse the cookies just fetched
        if _cleared and _cleared[0] is client and time.monotonic() - _cleared[1] < 30:
            return
        proxies = _proxies()
        try:
            cookies = await _browser_cookies(proxies[_proxy_index % len(proxies)] if proxies else None)
        except ApiError:
            raise
        except Exception as e:
            raise ApiError(f"masterkala.com bot check was not cleared by the browser ({type(e).__name__}).", 403) from e
        for c in cookies:
            client.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
        _cleared = (client, time.monotonic())


def _retry_after(r: httpx.Response) -> float | None:
    """Seconds from a numeric Retry-After on a 429/503, else None (HTTP-date form is ignored)."""
    v = r.headers.get("retry-after", "")
    return float(v) if r.status_code in (429, 503) and v.replace(".", "", 1).isdigit() else None


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
