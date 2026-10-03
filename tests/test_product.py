import json

import httpx
import pytest
from conftest import fixture

pytestmark = pytest.mark.anyio


async def test_mk_product(client, api):
    api["/product/24855/x"] = fixture("product_24855.html")
    api["product/getproductattribute"] = fixture("attributes_24855.json")
    api["productreview/getproductreviews"] = fixture("reviews.json")
    p = (await client.call_tool("mk_product", {"product_id": 24855})).structured_content
    # inline state is Toman (the JSON-LD says 94,990,000 IRR)
    assert (p["final_price"], p["price"], p["discount_pct"]) == (9499000, 11900000, 20)
    # rating from the reviews API, not the JSON-LD's floored 4 / 22
    assert p["brand"] == "CMF" and p["sku"] == "173090" and p["rating"] == 4.67 and p["review_count"] == 3
    assert p["in_stock"] is True and p["stock_status"] == "موجود" and p["stock_count"] == 43
    assert p["categories"] == [
        {"id": 588, "title": "لوازم صوتی"},
        {"id": 606, "title": "هندزفری بلوتوث دو گوش (بی سیم)"},
    ]
    colors = p["options"][0]
    assert colors["name"] == "color" and {v["name"] for v in colors["values"]} == {"سفید", "آبی", "مشکی"}
    assert all(v["available"] for v in colors["values"]) and p["options"][1]["name"] == "warranty"
    assert p["branches"] == [] and p["video"].endswith("407.mp4")
    assert {"productids": ["24855"], "compare": "1"} in [api.body(i) for i in (1, 2)]


async def test_mk_product_without_offer(client, api):
    # price above final_price but has_offer false: the site shows one price, no discount
    api["/product/24855/x"] = fixture("product_24855.html") + "\n  has_offer: false,\n"
    api["product/getproductattribute"] = fixture("attributes_24855.json")
    api["productreview/getproductreviews"] = {"count": "0", "rating_group": [], "list": []}
    p = (await client.call_tool("mk_product", {"product_id": 24855})).structured_content
    assert (p["final_price"], p["price"], p["discount_pct"]) == (9499000, 9499000, 0)
    assert p["rating"] is None and p["review_count"] == 0


async def test_mk_product_out_of_stock_falls_back(client, api):
    api["/product/26634/x"] = fixture("product_26634.html")
    api["product/getproductattribute"] = lambda r: httpx.Response(500)
    api["productreview/getproductreviews"] = fixture("reviews.json")
    p = (await client.call_tool("mk_product", {"product_id": 26634})).structured_content
    assert p["in_stock"] is False and p["stock_status"] == "ناموجود !"
    assert p["final_price"] == 4875000 and p["options"] == []
    assert "stock_count" not in p and "HTTP 500" in p["errors"][0]


async def test_mk_product_branches(client, api):
    api["/product/27034/x"] = fixture("product_27034.html")
    api["product/getproductattribute"] = {"products": [{"product_id": "27034", "quantity": "2"}], "items": []}
    api["productreview/getproductreviews"] = fixture("reviews.json")
    p = (await client.call_tool("mk_product", {"product_id": 27034})).structured_content
    assert p["branches"] == ["شعبه 1 مسترکالا (پاساژ چارسو)"]
    assert p["discount_pct"] == 20 and p["stock_count"] == 2


async def test_mk_product_not_found(client, api):
    result = await client.call_tool("mk_product", {"product_id": 9999999})
    assert result.is_error and "HTTP 404" in result.content[0].text


async def test_mk_specs(client, api):
    api["product/getproductattribute"] = fixture("attributes.json")
    out = (await client.call_tool("mk_specs", {"product_ids": [27144, 20850]})).structured_content
    # returned in request order, although the API answers 20850 first
    assert [(p["id"], p["stock_count"]) for p in out["products"]] == [(27144, 23), (20850, 4)]
    assert out["specs"][1] == {
        "group": "مشخصات فیزیکی",
        "name": "وزن",
        "values": {"27144": "120 گرم", "20850": "اعلام نشده"},
    }
    assert len(out["specs"]) == 5 and api.body() == {"productids": ["27144", "20850"], "compare": "1"}
    assert "not_found" not in out
    out = (await client.call_tool("mk_specs", {"product_ids": [27144, 9999999]})).structured_content
    assert [p["id"] for p in out["products"]] == [27144] and out["not_found"] == [9999999]


async def test_mk_specs_limits(client, api):
    result = await client.call_tool("mk_specs", {"product_ids": [1, 2, 3, 4, 5]})
    assert result.is_error and not api.calls
    api["product/getproductattribute"] = {"products": [], "items": []}
    result = await client.call_tool("mk_specs", {"product_ids": [1]})
    assert result.is_error and "mk_search" in result.content[0].text


async def test_mk_reviews(client, api):
    api["productreview/getproductreviews"] = fixture("reviews.json")
    out = (await client.call_tool("mk_reviews", {"product_id": 20850, "limit": 2})).structured_content
    assert out["count"] == 3 and out["average"] == 4.67
    assert out["star_counts"] == {"5": 2, "4": 1, "3": 0, "2": 0, "1": 0}
    assert [r["rating"] for r in out["reviews"]] == [4, 5]
    assert out["reviews"][0]["author"] == "آرش" and out["reviews"][0]["reply"] is None
    # read-only: never a `data` object, which would post a review
    assert api.body() == {"product_id": "20850", "from": 0, "limit": 25, "rating": 0}


async def test_mk_reviews_pages_and_sorts(client, api):
    rows = fixture("reviews.json")["list"]

    def pages(request):  # 30 reviews, 25 per page; the second page holds the newest
        start = json.loads(request.content)["from"]
        page = [
            {**rows[0], "date_added": f"2024-01-{d:02} 10:00:00"} for d in range(start + 1, min(start + 25, 30) + 1)
        ]
        if start:
            page[-1] = {**page[-1], "date_added": "2026-09-05 10:00:00", "rating": "3"}
        return httpx.Response(200, json={"count": "30", "rating_group": [], "list": page})

    api["productreview/getproductreviews"] = pages
    out = (await client.call_tool("mk_reviews", {"product_id": 24855, "limit": 30})).structured_content
    assert len(out["reviews"]) == 30 and [api.body(i)["from"] for i in (0, 1)] == [0, 25]
    assert out["reviews"][0]["date"].startswith("2026-09-05") and out["reviews"][0]["rating"] == 3


async def test_mk_shipping(client, api):
    api["product/getshippinghint"] = fixture("shipping.json")
    api["page/collect"] = fixture("delivery_badge.json")
    out = (await client.call_tool("mk_shipping", {"product_id": 27144})).structured_content
    assert out["tehran"] == {"when": "شنبه ۱۱ مهر 15:00 الی 18:00", "fee": 150000}
    assert out["other_cities"] == {"when": "فردا یکشنبه ۱۲ مهر", "fee": 155000}
    assert out["free_shipping_from"] == 5000000 and out["same_day_seconds_left"] > 0


async def test_mk_shipping_never_free_and_badge_down(client, api):
    hint = fixture("shipping.json")
    hint["debug"]["free_shipping_price"] = 90000000000  # bulky item: never free
    api["product/getshippinghint"] = hint
    api["page/collect"] = lambda r: httpx.Response(500)
    out = (await client.call_tool("mk_shipping", {"product_id": 26098})).structured_content
    assert out["free_shipping_from"] is None and out["tehran"]["fee"] == 150000
    assert out["same_day_seconds_left"] is None and "HTTP 500" in out["errors"][0]


async def test_mk_shipping_free_and_unavailable(client, api):
    api["product/getshippinghint"] = fixture("shipping_free.json")
    api["page/collect"] = fixture("delivery_badge.json")
    out = (await client.call_tool("mk_shipping", {"product_id": 24855})).structured_content
    assert out["tehran"]["fee"] == 0 and out["other_cities"]["fee"] == 0
    api["product/getshippinghint"] = {"debug": [], "shipping_hint": ""}  # real reply for an out-of-stock product
    result = await client.call_tool("mk_shipping", {"product_id": 26634})
    assert result.is_error and "out of stock" in result.content[0].text


async def test_mk_branches(client, api):
    api["/stores"] = fixture("stores.html")
    out = (await client.call_tool("mk_branches", {})).structured_content
    assert out["branches"][0] == {
        "name": "پاساژ چارسو",
        "address": "تهران ، جمهوری ، پاساژ چارسو ، طبقه 2 واحد D6",
        "phone": "02166172337",
        "lat": 35.6947482,
        "long": 51.412506,
    }
    assert len(out["branches"]) == 2
