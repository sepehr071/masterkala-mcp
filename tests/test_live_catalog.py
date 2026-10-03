import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.live]


async def call(client, name, args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def test_mk_search(client):
    data = await call(client, "mk_search", {"query": "هندزفری", "limit": 5})
    assert data["total"] > 100 and len(data["products"]) == 5
    assert data["products"][0]["in_stock"] and data["products"][0]["final_price"] > 0
    assert data["categories"] and all(c["id"] for c in data["categories"])


async def test_mk_find_cheapest(client):
    data = await call(client, "mk_find_cheapest", {"query": "پاوربانک", "limit": 10})
    prices = [o["final_price"] for o in data["offers"]]
    assert prices and prices == sorted(prices) and prices[0] > 0
    assert all("پاوربانک" in o["title"] for o in data["offers"])


async def test_mk_browse(client):
    data = await call(
        client, "mk_browse", {"category_id": 606, "min_price": 3000000, "max_price": 5000000, "limit": 12}
    )
    prices = [p["final_price"] for p in data["products"] if p["in_stock"]]
    assert prices == sorted(prices) and all(3000000 <= p <= 5000000 for p in prices)
    assert data["last_page"] >= 0


async def test_mk_filters(client):
    data = await call(client, "mk_filters", {"brand": "mcdodo"})
    assert data["max_price"] > 0 and data["filters"]
    colors = next(g for g in data["filters"] if g["group"] == "رنگ")
    assert all(k.startswith("o") for k in colors["options"])


async def test_mk_categories(client):
    data = await call(client, "mk_categories", {})
    assert len(data["categories"]) > 50 and any(c["id"] == 606 for c in data["categories"])


async def test_mk_brands(client):
    data = await call(client, "mk_brands", {"query": "mcdodo"})
    assert data["brands"] == [{"slug": "mcdodo", "name": "Mcdodo"}]


async def test_mk_deals(client):
    data = await call(client, "mk_deals", {"limit": 5})
    pcts = [d["discount_pct"] for d in data["deals"]]
    assert pcts and pcts == sorted(pcts, reverse=True) and all(d["final_price"] < d["price"] for d in data["deals"])
