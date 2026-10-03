import httpx
import pytest

pytestmark = pytest.mark.anyio

REVIEWS = {"list": [], "count": "0", "rating_group": [], "success": "1"}


async def test_all_tools_are_read_only(client):
    tools = (await client.list_tools()).tools
    assert len(tools) == 14
    for t in tools:
        assert t.name.startswith("mk_"), t.name
        assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False, t.name
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
    assert len(api.calls) == 2


async def test_timeout_is_not_retried(client, api):
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    api["productreview/getproductreviews"] = slow
    result = await client.call_tool("mk_reviews", {"product_id": 1})
    assert result.is_error and "did not answer in time" in result.content[0].text and len(api.calls) == 1


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
    assert sent.headers["Authorization"] == "" and "Chrome" in sent.headers["User-Agent"]
