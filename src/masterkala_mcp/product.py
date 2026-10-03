"""One product: details, specs, reviews, shipping; plus the physical branches."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable
from typing import Annotated, Any

from pydantic import Field

from .catalog import _first, _text
from .http import BASE, ApiError, api, get_page
from .registry import tool

ProductId = Annotated[
    int, Field(ge=1, le=10_000_000, description="MasterKala product id from mk_search / mk_browse, e.g. 24855.")
]

OPTION_NAMES = {"14": "color", "15": "warranty"}


@tool("Product details")
async def mk_product(product_id: ProductId) -> dict[str, Any]:
    """Get one product's full record: price and discount (Toman), stock status and count, colors and
    which are buyable, brand, category path, rating, and the physical branches that have it.

    Use after mk_search / mk_browse when the user picks a product. Specs table: mk_specs.
    Reviews: mk_reviews. Delivery date and fee: mk_shipping.
    """
    url, doc = await get_page(f"/product/{product_id}/x")  # any slug redirects to the canonical one
    ld = _json_ld(doc)
    item = next((x for x in ld if x.get("@type") == "Product"), None)
    if item is None:
        raise ApiError(f"No product {product_id} on masterkala.com. Get ids from mk_search.")

    # Inline page state is Toman; JSON-LD offers are Rial.
    prices = re.search(r"price: ([\d.]+),\s*price_with_discount: ([\d.]+)", doc)
    if prices:
        price, final = (int(float(x)) for x in prices.groups())
    else:
        price = final = int((item.get("offers") or {}).get("lowPrice") or 0) // 10
    if final >= price or "has_offer: false" in doc:  # no offer: the site shows only the final price
        price = final
    badge = _first(r'rounded-bl-2xl px-3 py-5 w-fit text-xs text-white[^"]*">\s*([^<]+?)\s*</div>', doc)
    breadcrumbs = next((x for x in ld if x.get("@type") == "BreadcrumbList"), {})
    video = next((x for x in ld if x.get("type") == "VideoObject"), {})

    result: dict[str, Any] = {
        "id": product_id,
        "title": item.get("name"),
        "brand": (item.get("brand") or {}).get("name"),
        "sku": item.get("sku"),
        "final_price": final or None,
        "price": price or None,
        "discount_pct": 100 * (price - final) // price if price and final else 0,  # the site floors
        "in_stock": badge is None and bool(final),
        "stock_status": badge or "موجود",
        # The JSON-LD aggregateRating is SEO filler (integer, plus an editorial review); use the reviews API.
        "rating": None,
        "review_count": None,
        "categories": [
            {"id": int(m.group(1)), "title": e["item"].get("name")}
            for e in breadcrumbs.get("itemListElement") or []
            if (m := re.search(r"/categories/(\d+)/", e.get("item", {}).get("@id", "")))
        ],
        "options": _options(doc),
        "branches": [
            _text(b)
            for b in re.findall(
                r'class="font-bold">(.*?)</div>',
                _first(r'x-ref="shop_inventory_box">(.*?)<div\s+class="section-device-controller', doc) or "",
            )
        ],
        "description": item.get("description") or None,
        "image": (item.get("image") or [None])[0],
        "video": video.get("contentUrl"),
        "url": url,
    }
    errors: list[str] = []
    stock, reviews = await asyncio.gather(
        _soft("stock_count", _attributes([product_id]), errors), _soft("rating", _reviews(product_id), errors)
    )
    if stock is not None:
        p = stock["products"][0] if stock.get("products") else {}
        result["stock_count"] = int(p.get("quantity") or 0)
    if reviews is not None:
        result["rating"], counts = _rating(reviews)
        result["review_count"] = sum(counts.values())
    if errors:
        result["errors"] = errors
    return result


@tool("Specs and comparison")
async def mk_specs(
    product_ids: Annotated[
        list[Annotated[int, Field(ge=1, le=10_000_000)]],
        Field(min_length=1, max_length=4, description="1 to 4 product ids, e.g. [27144, 20850]."),
    ],
) -> dict[str, Any]:
    """Get the specification table of 1-4 products side by side, with each product's stock count.

    Use for "battery life / Bluetooth version of X" or to compare products row by row. Each
    spec row has one value per product id; a missing id means no value for that product. Ids that do not exist are listed in not_found.
    """
    data = await _attributes(product_ids)
    products = {str(p.get("product_id")): p for p in data.get("products") or []}
    if not products:
        raise ApiError("None of these product ids exist on masterkala.com. Get ids from mk_search.")
    return {
        "products": [
            {
                "id": int(pid),
                "title": products[pid].get("name"),
                "stock_count": int(products[pid].get("quantity") or 0),
                "url": f"{BASE}/product/{pid}/{products[pid].get('slug') or 'x'}",
            }
            for pid in map(str, product_ids)
            if pid in products
        ],
        **({"not_found": missing} if (missing := [i for i in product_ids if str(i) not in products]) else {}),
        "specs": [
            {
                "group": g.get("group_name"),
                "name": a.get("name"),
                "values": {k: (v or "").strip() for k, v in (a.get("product_texts") or {}).items()},
            }
            for g in data.get("items") or []
            for a in g.get("attributes") or []
        ],
    }


@tool("Product reviews")
async def mk_reviews(
    product_id: ProductId,
    stars: Annotated[int, Field(ge=0, le=5, description="Only reviews with this many stars (1-5); 0 = all.")] = 0,
    limit: Annotated[int, Field(ge=1, le=100, description="Max reviews to return, newest first.")] = 20,
) -> dict[str, Any]:
    """Read customer reviews of a product (1-5 stars, newest first) with the store's replies and the star breakdown.

    Use as a quality check before recommending a product. average and star_counts cover all
    reviews; count is the number matching `stars`.
    """
    body = await _reviews(product_id, 0, stars)
    count, rows = int(body.get("count") or 0), body.get("list") or []
    while len(rows) < min(limit, count):  # the site sends at most 25 per page
        more = (await _reviews(product_id, len(rows), stars)).get("list") or []
        if not more:
            break
        rows += more
    # ponytail: pages are only roughly by date, so "newest" is among the fetched pages; fetch all if it matters.
    rows.sort(key=lambda r: r.get("date_added") or "", reverse=True)
    average, groups = _rating(body)
    return {
        "count": count,
        "average": average,
        "star_counts": {str(r): groups.get(r, 0) for r in range(5, 0, -1)},
        "reviews": [
            {
                "author": (r.get("author") or "").strip(),
                "rating": int(r.get("rating") or 0),
                "date": r.get("date_added"),
                "text": (r.get("text") or "").strip(),
                "reply": (r.get("reply") or "").strip() or None,
            }
            for r in rows[:limit]
        ],
    }


@tool("Delivery date and fee")
async def mk_shipping(product_id: ProductId) -> dict[str, Any]:
    """Get the nearest delivery slot and shipping fee for one product: Tehran courier and post to other cities.

    Use for "when will it arrive / how much is shipping". Fees are Toman, 0 = free. Shipping is
    free when the basket reaches free_shipping_from; null means this item never ships free
    (bulky goods). same_day_seconds_left > 0 means an order placed now can still arrive today in
    Tehran. Estimates use a default Tehran address.
    """
    errors: list[str] = []
    hint, badge = await asyncio.gather(
        api("product/getshippinghint", {"product_id": str(product_id)}),
        _soft("same_day_seconds_left", api("page/collect", {}), errors),
    )
    text = hint.get("shipping_hint") or ""
    if not text:
        raise ApiError(f"No delivery estimate for product {product_id}: it is out of stock or does not exist.")
    lines = re.split(r"<br\s*/?>", text)
    debug = hint.get("debug") or {}
    free_from = debug.get("free_shipping_price") if isinstance(debug, dict) else None
    seconds = _first(r'data-seconds="(\d+)"', (badge or {}).get("embed_html") or "")
    return {
        "tehran": _slot(next((x for x in lines if "تهران" in x), "")),
        "other_cities": _slot(next((x for x in lines if "شهرستان" in x), "")),
        # bulky items carry 90,000,000,000: never free
        "free_shipping_from": free_from if free_from and free_from < 10**10 else None,
        "same_day_seconds_left": int(seconds) if seconds else None,
        "text": _text(text),
        **({"errors": errors} if errors else {}),
    }


@tool("Physical branches")
async def mk_branches() -> dict[str, Any]:
    """List MasterKala's physical shops in Tehran with address, phone and map location.

    Use when the user wants to buy in person. mk_product's `branches` says which shops have a
    given product; call the shop before going, they stock only part of the catalog.
    """
    _, doc = await get_page("/stores")
    branches = []
    for block in re.split(r'<use href="#shop">', doc)[1:]:
        name = _first(r"</svg>\s*</div>\s*([^<]+?)\s*</div>", block)
        address = _first(r"mdi-map-marker[^>]*></i>\s*([^<]+?)\s*</div>", block)
        if not (name and address):
            continue
        loc = re.search(r"@([\d.]+),([\d.]+)", block)
        branches.append(
            {
                "name": name,
                "address": address,
                "phone": _first(r'href="tel:([\d+]+)"', block),
                "lat": float(loc.group(1)) if loc else None,
                "long": float(loc.group(2)) if loc else None,
            }
        )
    return {"branches": branches}


async def _attributes(product_ids: list[int]) -> dict[str, Any]:
    # compare "1" is the grid with the real stock count; "0" is a bare list without it.
    data = await api("product/getproductattribute", {"productids": [str(i) for i in product_ids], "compare": "1"})
    return data if isinstance(data, dict) else {}


async def _reviews(product_id: int, offset: int = 0, stars: int = 0) -> dict[str, Any]:
    # Read-only: never send a `data` object here, the same route posts a review with it.
    return await api(
        "productreview/getproductreviews", {"product_id": str(product_id), "from": offset, "limit": 25, "rating": stars}
    )


def _rating(body: dict[str, Any]) -> tuple[float | None, dict[int, int]]:
    """Average stars over all reviews (None if none) and the count per star."""
    groups = {int(g["rating"]): int(g["count"]) for g in body.get("rating_group") or []}
    total = sum(groups.values())
    return (round(sum(r * n for r, n in groups.items()) / total, 2) if total else None), groups


async def _soft(name: str, call: Awaitable[Any], errors: list[str]) -> Any:
    """Await an optional extra call; on failure note it in `errors` and return None."""
    try:
        return await call
    except ApiError as e:
        errors.append(f"{name}: {e}")
        return None


def _json_ld(doc: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in re.findall(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", doc, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        items += data if isinstance(data, list) else [data]
    return [x for x in items if isinstance(x, dict)]


def _options(doc: str) -> list[dict[str, Any]]:
    """Variants (color, warranty) from the inline page state; available = buyable now."""
    raw = _first(r"\n\s*optionList: (\[.*?\]),\n", doc)
    if not raw:
        return []
    state = _first(r"\n\s*available: (\{.*?\}),\n", doc)
    buyable = {str(v) for v in json.loads(state).get("option_values_available") or []} if state else set()
    return [
        {
            "name": OPTION_NAMES.get(o.get("option_id"), (o.get("name") or "").strip()),
            "values": [
                {
                    "id": int(v["option_value_id"]),
                    "name": (v.get("name") or "").strip(),
                    "available": v["option_value_id"] in buyable,
                }
                for v in o.get("product_option_value") or []
            ],
        }
        for o in json.loads(raw)
    ]


def _slot(line: str) -> dict[str, Any] | None:
    """'ارسال تهران: <b>شنبه ۱۱ مهر 15:00 الی 18:00</b> هزینه <b>150,000 تومان</b>' -> when + fee."""
    if not line:
        return None
    when = _first(r"<b>(.*?)</b>", line)
    fee = _first(r"هزینه\s*<b>([\d,]+)", line)
    return {"when": _text(when), "fee": int(fee.replace(",", "")) if fee else 0 if "رایگان" in line else None}
