import sys

import httpx
import pytest

from masterkala_mcp import http

pytestmark = pytest.mark.anyio

REVIEWS = {"list": [], "count": "0", "rating_group": [], "success": "1"}


async def test_all_tools_are_read_only(client):
    tools = (await client.list_tools()).tools
    assert len(tools) == 14
    for t in tools:
        assert t.name.startswith("mk_"), t.name
        assert t.annotations.read_only_hint is True, t.name
        assert t.description and t.title, t.name


async def test_dropped_connection_is_retried_once(client, api):
    attempts = []

    def flaky(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.", request=request)
        return httpx.Response(200, json=REVIEWS)

    api["productreview/getproductreviews"] = flaky
    result = await client.call_tool("mk_reviews", {"product_id": 1})
    assert not result.is_error and len(attempts) == 2


async def test_network_error_after_retry(client, api):
    def down(request):
        raise httpx.ConnectError("[SSL: UNEXPECTED_EOF_WHILE_READING]", request=request)

    api["productreview/getproductreviews"] = down
    result = await client.call_tool("mk_reviews", {"product_id": 1})
    assert result.is_error and "Could not reach masterkala.com (ConnectError)" in result.content[0].text
    assert len(api.calls) == 3  # first try + MAX_RETRIES


async def test_timeout_is_retried_then_reported(client, api):
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    api["productreview/getproductreviews"] = slow
    result = await client.call_tool("mk_reviews", {"product_id": 1})
    assert result.is_error and "did not answer in time" in result.content[0].text and len(api.calls) == 3


@pytest.mark.parametrize(
    ("status", "text"),
    [(404, "HTTP 404"), (429, "rate limiting"), (500, "server error (HTTP 500)"), (403, "blocked")],
)
async def test_http_errors_are_actionable(client, api, status, text):
    api["productreview/getproductreviews"] = lambda r: httpx.Response(status)
    result = await client.call_tool("mk_reviews", {"product_id": 1})
    assert result.is_error and text in result.content[0].text


async def test_body_level_errors(client, api):
    api["productreview/getproductreviews"] = {"success": "0", "message": "invalid product"}
    result = await client.call_tool("mk_reviews", {"product_id": 1})
    assert result.is_error and "invalid product" in result.content[0].text

    api["productreview/getproductreviews"] = lambda r: httpx.Response(200, text="null")
    result = await client.call_tool("mk_reviews", {"product_id": 1})
    assert result.is_error and "no data" in result.content[0].text

    api["productreview/getproductreviews"] = lambda r: httpx.Response(200, text="<html>oops</html>")
    result = await client.call_tool("mk_reviews", {"product_id": 1})
    assert result.is_error and "non-JSON" in result.content[0].text


async def test_guest_request_format(client, api):
    api["productreview/getproductreviews"] = REVIEWS
    await client.call_tool("mk_reviews", {"product_id": 1})
    sent = api.calls[0]
    assert sent.method == "POST" and sent.url.path == "/api/2.1.1.0.0/"
    assert sent.headers["Authorization"] == "" and sent.headers["Content-Type"] == "text/plain;charset=UTF-8"
    assert sent.headers["Origin"] == "https://masterkala.com" and sent.headers["sec-fetch-site"] == "same-origin"


async def test_403_is_not_retried(client, api):
    api["productreview/getproductreviews"] = lambda r: httpx.Response(403, text="<html>Forbidden</html>")
    assert (await client.call_tool("mk_reviews", {"product_id": 1})).is_error and len(api.calls) == 1


def test_is_challenge():
    html = {"content-type": "text/html"}
    assert http._is_challenge(httpx.Response(403, text="<html>Just a moment...</html>", headers=html))
    assert not http._is_challenge(httpx.Response(403, text="<html>Forbidden</html>", headers=html))
    assert not http._is_challenge(httpx.Response(200, text="<html></html>", headers=html))


async def test_proxy_list_rotates_and_stale_client_does_not(monkeypatch, api):
    monkeypatch.setenv("MASTERKALA_MCP_PROXY", "http://p1:1, http://p2:2")
    assert http._proxies() == ["http://p1:1", "http://p2:2"]
    old, _ = http._get_client()
    http._next_proxy(old)
    new, _ = http._get_client()
    assert http._proxy_index == 1 and new is not old
    http._next_proxy(old)  # a late failure on the retired client must not skip the proxy now in use
    assert http._proxy_index == 1 and http._client is new


async def test_challenge_cleared_by_browser_once(monkeypatch, api):
    runs = []

    async def fake_browser(proxy):
        runs.append(proxy)
        return [{"name": "clearance", "value": "ok", "domain": "masterkala.com", "path": "/"}]

    monkeypatch.setattr(http, "_browser_cookies", fake_browser)

    def guarded(request):
        if "clearance=ok" not in request.headers.get("cookie", ""):
            return httpx.Response(403, text="<html>Just a moment</html>", headers={"content-type": "text/html"})
        return httpx.Response(200, json=REVIEWS)

    api["productreview/getproductreviews"] = guarded
    assert await http.api("productreview/getproductreviews", {}) == REVIEWS
    assert len(runs) == 1 and len(api.calls) == 2


async def test_challenge_without_patchright(monkeypatch, api):
    monkeypatch.setitem(sys.modules, "patchright.async_api", None)  # makes the import fail
    api["productreview/getproductreviews"] = lambda r: httpx.Response(403, text="<html>Just a moment</html>")
    with pytest.raises(http.ApiError, match=r"masterkala-mcp\[browser\].*patchright install chromium"):
        await http.api("productreview/getproductreviews", {})


async def test_retry_after_is_honoured_and_capped(monkeypatch, api):
    waits = []

    async def fake_sleep(s):
        waits.append(s)

    monkeypatch.setattr(http.asyncio, "sleep", fake_sleep)
    hits = []

    def limited(request):
        hits.append(1)
        if len(hits) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        if len(hits) == 2:
            return httpx.Response(503, headers={"Retry-After": "999"})
        return httpx.Response(200, json=REVIEWS)

    api["productreview/getproductreviews"] = limited
    await http.api("productreview/getproductreviews", {})
    assert len(hits) == 3 and [w for w in waits if w] == [3, http.MAX_RETRY_WAIT]
