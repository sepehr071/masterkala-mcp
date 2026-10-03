import json
from pathlib import Path

import httpx
import pytest
from mcp import Client

from masterkala_mcp import http
from masterkala_mcp.server import mcp

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str):
    """A recorded response: parsed JSON for .json files, the HTML text otherwise."""
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return json.loads(text) if name.endswith(".json") else text


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fresh_http_client():
    """The shared httpx client is bound to one event loop; each test gets a new loop."""
    http.set_transport(None)
    yield
    http.set_transport(None)


@pytest.fixture
def api():
    """Route table for a fake masterkala.com.

    Keys are the API route for /api/ calls (api["product/searchproduct"]) and the URL path
    otherwise (api["/offer"]). Values: a dict/list (JSON), a str (HTML), or a callable(request)
    -> httpx.Response. Unknown keys return 404. Every request is appended to api.calls.
    """

    class Routes(dict):
        calls: list[httpx.Request]

        def body(self, i: int = -1):
            return json.loads(self.calls[i].content)

    routes = Routes()
    routes.calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        routes.calls.append(request)
        target = routes.get(request.url.params.get("route") or request.url.path)
        if target is None:
            return httpx.Response(404, text="not found")
        if callable(target):
            return target(request)
        if isinstance(target, str):
            return httpx.Response(200, text=target, headers={"content-type": "text/html; charset=UTF-8"})
        return httpx.Response(200, json=target)

    http.set_transport(httpx.MockTransport(handler))
    return routes


@pytest.fixture
async def client():
    async with Client(mcp, raise_exceptions=True) as c:
        yield c
