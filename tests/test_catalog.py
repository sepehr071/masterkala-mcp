import json

import httpx
import pytest
from conftest import fixture

pytestmark = pytest.mark.anyio


async def test_mk_search(client, api):
    api["product/searchproduct"] = fixture("search.json")
    result = await client.call_tool("mk_search", {"query": "پاوربانک شیائومی", "page": 1, "limit": 8})
    out = result.structured_content
    assert out["total"] == 83 and len(out["products"]) == 8
    assert out["products"][2] == {
        "id": 26935,
        "title": "پاوربانک 10000 شیائومی گلوریمی Glorimi LightCore توان 22.5 وات",
        "final_price": 4188000,
        "price": 4410000,
        "discount_pct": 5,
        "in_stock": True,
        "stock_status": "موجود",
        "label": None,
        "low_stock": None,
        "url": "https://masterkala.com/product/26935/glorimi-lightCore-power-10000-bank-22-5w",
    }
    # branch-only items have no online price
    assert out["products"][6]["final_price"] is None and out["products"][6]["in_stock"] is False
    assert out["pages"] == [{"title": "پاوربانک Xiaomi", "url": "https://masterkala.com/tag/22499/Xiaomi-Power-Bank"}]
    sent = api.body()
    assert sent == {"v": "1.2", "query": "پاوربانک شیائومی", "from": 8, "limit": 8, "filter": ""}
    assert api.calls[0].headers["Authorization"] == ""


async def test_mk_search_in_stock_only(client, api):
    api["product/searchproduct"] = fixture("search.json")
    out = (await client.call_tool("mk_search", {"query": "پاوربانک", "in_stock_only": True})).structured_content
    assert len(out["products"]) == 6 and all(p["in_stock"] for p in out["products"])


async def test_mk_find_cheapest(client, api):
    api["product/searchproduct"] = fixture("search.json")
    out = (await client.call_tool("mk_find_cheapest", {"query": "پاوربانک شیائومی"})).structured_content
    # covers and branch-only items are dropped; cheapest payable price first
    assert [(o["id"], o["final_price"]) for o in out["offers"]] == [
        (26935, 4188000),
        (26934, 5401000),
        (26976, 7470000),
        (27035, 18164000),
    ]
    assert [o["free_shipping"] for o in out["offers"]] == [False, True, True, True]
    assert out["scanned"] == 8 and out["complete"] and api.body()["limit"] == 500


async def test_mk_find_cheapest_pages_until_out_of_stock(client, api):
    item = fixture("search.json")["products"][0]

    def search(request):
        body = json.loads(request.content)
        stock = "1" if body["from"] == 0 else "0"  # first page all in stock, second reaches out-of-stock items
        return httpx.Response(200, json={"count": 1200, "products": [{**item, "quantity": stock}] * body["limit"]})

    api["product/searchproduct"] = search
    out = (await client.call_tool("mk_find_cheapest", {"query": "پاوربانک", "scan": 1500})).structured_content
    assert [api.body(i)["from"] for i in range(len(api.calls))] == [0, 500]
    assert out["scanned"] == 1000 and out["complete"]
    out = (await client.call_tool("mk_find_cheapest", {"query": "پاوربانک", "scan": 400})).structured_content
    assert out["scanned"] == 400 and not out["complete"]  # in-stock items go on past the scan


async def test_mk_find_cheapest_never_free_shipping(client, api):
    data = fixture("search.json")
    next(p for p in data["products"] if p["product_id"] == "27035")["no_free_shipping"] = "1"
    api["product/searchproduct"] = data
    out = (await client.call_tool("mk_find_cheapest", {"query": "پاوربانک شیائومی"})).structured_content
    assert [o["free_shipping"] for o in out["offers"]] == [False, True, True, False]


async def test_mk_search_no_offer(client, api):
    data = fixture("search.json")
    data["products"][2].update(price="4100000.0000", percent="-2")  # price below final: no offer on the site
    api["product/searchproduct"] = data
    out = (await client.call_tool("mk_search", {"query": "پاوربانک"})).structured_content
    assert (out["products"][2]["price"], out["products"][2]["discount_pct"]) == (4188000, 0)


async def test_mk_find_cheapest_keeps_accessories_on_request(client, api):
    api["product/searchproduct"] = fixture("search.json")
    out = (await client.call_tool("mk_find_cheapest", {"query": "کاور پاوربانک"})).structured_content
    assert [o["id"] for o in out["offers"]] == [16649, 16650]
    out = (
        await client.call_tool("mk_find_cheapest", {"query": "پاوربانک", "include_accessories": True, "limit": 2})
    ).structured_content
    assert [o["final_price"] for o in out["offers"]] == [44500, 145000]


async def test_mk_browse(client, api):
    api["/fetch_content/product_list"] = fixture("product_list.html")
    args = {
        "category_id": 606,
        "sort": "most_stock",
        "filter_ids": ["m30", "o52"],
        "page": 2,
        "limit": 10,
    }
    out = (await client.call_tool("mk_browse", args)).structured_content
    assert out["title"] == "انواع هندزفری بلوتوث با مدل های مختلف" and out["last_page"] == 5
    assert out["products"][0] == {
        "id": 25016,
        "title": "هندزفری بلوتوث اوی Awei T87 Mini Wireless Earbuds",
        "final_price": 1979000,
        "price": 1979000,
        "discount_pct": 0,
        "in_stock": True,
        "badges": ["فقط 2 عدد مونده!"],
        "url": "https://masterkala.com/product/25016/Awei-T87-TWS-Earbuds-Wireless-Headphones",
    }
    assert [p["in_stock"] for p in out["products"]] == [True, True, True, False, False]
    assert out["products"][3]["final_price"] is None
    # every key is sent (a partial body hangs the server), and a sort is always set
    assert api.body() == {
        "cat": "606",
        "manufacturer": "",
        "tag": "",
        "query": "",
        "from": 20,
        "limit": 10,
        "page": 2,
        "filter": "m30,o52",
        "search": "",
        "sort": "quantity desc",
        "price": "",
    }


async def test_mk_browse_price_range_on_final_price(client, api):
    api["/fetch_content/product_list"] = fixture("product_list.html")
    args = {"category_id": 606, "min_price": 2000000, "max_price": 2300000}
    out = (await client.call_tool("mk_browse", args)).structured_content
    # the site filters on the list price: send no max for sort=cheapest and cut on final_price here
    assert [p["id"] for p in out["products"]] == [27157] and api.body()["price"] == "2000000,10000000000"
    assert out["last_page"] == 0  # later pages are all above max_price
    await client.call_tool("mk_browse", {**args, "sort": "newest"})
    assert api.body()["price"] == "2000000,2300000"


async def test_mk_browse_needs_one_source(client, api):
    result = await client.call_tool("mk_browse", {"category_id": 606, "brand": "mcdodo"})
    assert result.is_error and "exactly one" in result.content[0].text and not api.calls
    result = await client.call_tool("mk_browse", {"brand": "../x"})
    assert result.is_error and not api.calls
    result = await client.call_tool("mk_browse", {"category_id": 606, "min_price": 5000000, "max_price": 1000000})
    assert result.is_error and "min_price" in result.content[0].text and not api.calls


async def test_mk_browse_unknown_id(client, api):
    api["/fetch_content/product_list"] = "<div><h1></h1></div>"  # the site's reply for an unknown category
    result = await client.call_tool("mk_browse", {"category_id": 99999999})
    assert result.is_error and "mk_categories" in result.content[0].text


async def test_mk_filters(client, api):
    api["/categories/163/products/x"] = fixture("category.html")
    out = (await client.call_tool("mk_filters", {"category_id": 163})).structured_content
    assert out["max_price"] == 36751000 and out["title"] == "انواع ساعت و مچ بند هوشمند در مدل های متنوع"
    brands, colors = out["filters"][0], out["filters"][1]
    assert brands == {"group": "برند", "options": {"m288": "1More", "m287": "70Mai", "m309": "Amazfit"}}
    assert len(colors["options"]) == 40 and colors["omitted"] == 5
    full = (await client.call_tool("mk_filters", {"category_id": 163, "group": "رنگ"})).structured_content
    assert [f["group"] for f in full["filters"]] == ["رنگ"] and len(full["filters"][0]["options"]) == 45
    result = await client.call_tool("mk_filters", {"category_id": 163, "group": "color"})
    assert result.is_error and "برند" in result.content[0].text


async def test_mk_filters_brand_and_unknown_page(client, api):
    api["/brand/mcdodo"] = "<html><h1>no listing</h1></html>"
    result = await client.call_tool("mk_filters", {"brand": "mcdodo"})
    assert result.is_error and "mk_categories" in result.content[0].text


async def test_mk_categories(client, api):
    api["/categories"] = fixture("categories.html")
    out = (await client.call_tool("mk_categories", {})).structured_content
    assert out["categories"][:2] == [
        {"id": 163, "title": "ساعت هوشمند", "slug": "Wearable-Gadget"},
        {"id": 881, "title": "ماساژور", "slug": "Massagers"},
    ]
    assert len(out["categories"]) == 5  # deduplicated
    out = (await client.call_tool("mk_categories", {"query": "power"})).structured_content
    assert [c["id"] for c in out["categories"]] == [64]


async def test_mk_brands(client, api):
    api["/brand"] = fixture("brands.html")
    out = (await client.call_tool("mk_brands", {"query": "anker"})).structured_content
    assert out["brands"] == [{"slug": "anker-fa", "name": "Anker"}]


async def test_mk_deals(client, api):
    api["/offer"] = fixture("offer.html")
    out = (await client.call_tool("mk_deals", {"limit": 3})).structured_content
    assert out["ends_in_seconds"] == 50340 and out["count"] == 4
    assert [(d["id"], d["discount_pct"]) for d in out["deals"]] == [(24855, 20), (27034, 20), (25491, 12)]
    assert out["deals"][0]["price"] == 11900000 and out["deals"][0]["final_price"] == 9499000


async def test_query_too_short_rejected(client, api):
    result = await client.call_tool("mk_search", {"query": "x"})
    assert result.is_error and not api.calls
