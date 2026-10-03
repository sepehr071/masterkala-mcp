import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.live]


async def call(client, name, args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def test_mk_product(client):
    data = await call(client, "mk_product", {"product_id": 24855})
    assert data["brand"] == "CMF" and data["price"] > 0 and data["final_price"] <= data["price"]
    assert data["options"] and data["options"][0]["name"] == "color"
    assert "errors" not in data and data["stock_count"] >= 0
    assert data["review_count"] >= 20 and 4 < data["rating"] <= 5  # reviews API, not the JSON-LD's floored 4


async def test_mk_specs(client):
    data = await call(client, "mk_specs", {"product_ids": [27144, 20850]})
    assert [p["id"] for p in data["products"]] == [27144, 20850] and data["specs"]


async def test_mk_reviews(client):
    data = await call(client, "mk_reviews", {"product_id": 20850})
    assert data["count"] >= 3 and all(1 <= r["rating"] <= 5 for r in data["reviews"])


async def test_mk_shipping(client):
    data = await call(client, "mk_shipping", {"product_id": 27144})
    assert data["free_shipping_from"] == 5000000 and data["tehran"]["when"]
    assert data["tehran"]["fee"] is not None


async def test_mk_branches(client):
    data = await call(client, "mk_branches", {})
    assert data["branches"] and all(b["address"] and b["phone"] for b in data["branches"])
