"""Finding products: search, cheapest offers, category / brand listings, filters, deals."""

from __future__ import annotations

import html
import json
import re
from typing import Annotated, Any, Literal

from pydantic import Field

from .http import BASE, ApiError, api, cached, get_page, product_list
from .registry import tool

Query = Annotated[
    str,
    Field(
        min_length=2,
        max_length=100,
        description="Persian or English keyword, e.g. 'هندزفری بلوتوث'.",
    ),
]
CategoryId = Annotated[int | None, Field(ge=1, description="From mk_categories or mk_search, e.g. 606.")]
BrandSlug = Annotated[
    str | None,
    Field(pattern=r"^[A-Za-z0-9-]{2,40}$", description="From mk_brands, e.g. 'mcdodo'."),
]
TagId = Annotated[int | None, Field(ge=1, description="From /tag/<id>/ links, e.g. 22246.")]

FREE_SHIPPING_FROM = 5_000_000  # Toman, basket total
IN_STOCK_TEXT = "موجود"  # stock_status of every buyable item; only other values are worth sending
# First title words of add-ons sold for another product (cover, case, bag, screen glass, protector, strap, sticker).
ACCESSORIES = {"کاور", "قاب", "کیف", "گلس", "محافظ", "بند", "برچسب"}

SORTS = {
    "cheapest": "price asc",
    "most_expensive": "price desc",
    "most_stock": "quantity desc",
    "newest": "date_added DESC",
}


@tool("Search products")
async def mk_search(
    query: Query,
    in_stock_only: Annotated[
        bool,
        Field(description="Drop items not buyable now (total still counts all matches)."),
    ] = False,
    page: Annotated[int, Field(ge=0, le=50, description="From 0.")] = 0,
    limit: Annotated[int, Field(ge=1, le=30, description="Products per page.")] = 10,
) -> dict[str, Any]:
    """Search MasterKala products by keyword: price, discount and stock of each match.

    Use first for "price of X". In-stock first. Also returns matching categories (ids for
    mk_browse) and brand/tag pages.
    """
    data = await _search(query, page * limit, limit)
    products = [_search_product(p) for p in data.get("products") or []]
    if in_stock_only:
        products = [p for p in products if p["in_stock"]]
    return {
        "total": int(data.get("count") or 0),
        "page": page,
        "products": products,
        "categories": [{"id": _link_id(c.get("link")), "title": c.get("name")} for c in data.get("sub") or []],
        "pages": [{"title": c.get("name"), "url": BASE + c["link"]} for c in data.get("pages") or [] if c.get("link")],
    }


@tool("Find cheapest product")
async def mk_find_cheapest(
    query: Query,
    scan: Annotated[
        int,
        Field(ge=20, le=1500, description="Max results to scan, 500 per request."),
    ] = 500,
    match_all_words: Annotated[bool, Field(description="Keep only titles containing every query word.")] = True,
    include_accessories: Annotated[
        bool,
        Field(description="Keep cases, covers, protectors, straps (dropped unless the query names them)."),
    ] = False,
    limit: Annotated[int, Field(ge=1, le=50, description="Max offers.")] = 20,
) -> dict[str, Any]:
    """Find the cheapest in-stock products for a keyword, one flat list sorted by final_price.

    Use for the lowest price of X. free_shipping = reaches 5,000,000 Toman (bulky items never).
    complete=false: more in-stock items past `scanned`; raise scan.
    """
    found: list[dict[str, Any]] = []
    while len(found) < scan:  # in-stock items come first: stop at the first page that reaches out-of-stock ones
        data = await _search(query, len(found), min(500, scan - len(found)))
        batch = data.get("products") or []
        found += batch
        if len(batch) < 500 or batch[-1].get("quantity") != "1":
            break
    words = _norm(query).split()
    offers = []
    for p in found:
        title = _norm(p.get("name") or "")
        if p.get("quantity") != "1" or (match_all_words and not all(w in title for w in words)):
            continue
        # ponytail: first-word heuristic; a "case for a power bank" starts with the case word.
        if not include_accessories and title.split(" ", 1)[0] in ACCESSORIES and not ACCESSORIES & set(words):
            continue
        offer = _search_product(p)
        # no_free_shipping "1": bulky items that never ship free.
        offer["free_shipping"] = (
            p.get("no_free_shipping") != "1" and (offer.get("final_price") or 0) >= FREE_SHIPPING_FROM
        )
        offers.append(offer)
    offers = [o for o in offers if o.get("final_price")]
    offers.sort(key=lambda o: o["final_price"])
    return {
        "scanned": len(found),
        "total_matches": int(data.get("count") or 0),
        # False: in-stock items continue past `scanned`; raise scan for a complete answer.
        "complete": not found or found[-1].get("quantity") != "1" or len(found) >= int(data.get("count") or 0),
        "offers": offers[:limit],
    }


@tool("Browse a category or brand")
async def mk_browse(
    category_id: CategoryId = None,
    brand: BrandSlug = None,
    tag_id: TagId = None,
    sort: Annotated[
        Literal["cheapest", "most_expensive", "most_stock", "newest"],
        Field(description="In-stock items always come first."),
    ] = "cheapest",
    min_price: Annotated[int | None, Field(ge=0, description="Min final_price, Toman.")] = None,
    max_price: Annotated[int | None, Field(ge=1, description="Max final_price, Toman.")] = None,
    filter_ids: Annotated[
        list[Annotated[str, Field(pattern=r"^[mo]?\d{1,6}$")]] | None,
        Field(
            max_length=10,
            description="Ids from mk_filters: 'm30' brand, 'o78' color, '117' attribute.",
        ),
    ] = None,
    page: Annotated[int, Field(ge=0, le=100, description="From 0.")] = 0,
    limit: Annotated[int, Field(ge=1, le=40, description="Per page.")] = 24,
) -> dict[str, Any]:
    """List the products of a category, brand or tag with sorting, price range and filters.

    Pass exactly one of category_id / brand / tag_id. No keyword search here: mk_search.
    """
    sources = {"cat": category_id, "manufacturer": brand, "tag": tag_id}
    if sum(v is not None for v in sources.values()) != 1:
        raise ApiError("Pass exactly one of category_id, brand or tag_id.")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ApiError("min_price must be <= max_price.")
    # The site filters on the list price but sells at final_price (<= list price): send min as is and,
    # for sort=cheapest (by final_price), no max, then drop cards outside the range below.
    # ponytail: other sorts keep the site's max, so discounted items listed above max_price are missed.
    price = ""
    if min_price is not None or max_price is not None:
        price = f"{min_price or 0},{(max_price if sort != 'cheapest' else None) or 10**10}"
    # Every key must be present (a partial body hangs), and a non-empty sort avoids a
    # server cache that ignores limit and price.
    body = {
        **{k: "" if v is None else str(v) for k, v in sources.items()},
        "query": "",
        "from": page * limit,
        "limit": limit,
        "page": page,
        "filter": ",".join(filter_ids or []),
        "search": "",
        "sort": SORTS[sort],
        "price": price,
    }
    fragment = await product_list(body)
    pages = [int(n) for n in re.findall(r"changePageNumber\((\d+)\)", fragment)]
    title, products = _text(_first(r"<h1[^>]*>(.*?)</h1>", fragment)) or None, _cards(fragment)
    if title is None and not products:  # a real listing keeps its title even when filtered to nothing
        raise ApiError(
            "No listing for this category_id / brand / tag_id. Get ids from mk_categories, mk_brands or mk_search."
        )
    if price:
        lo, hi = min_price or 0, max_price or 10**10
        if sort == "cheapest" and any((p["final_price"] or 0) > hi for p in products):
            pages = []  # sorted by final_price: every later page is above max_price
        products = [p for p in products if p["final_price"] is not None and lo <= p["final_price"] <= hi]
    return {"title": title, "page": page, "last_page": max(pages, default=page), "products": products}


@tool("Filters of a category or brand")
async def mk_filters(
    category_id: CategoryId = None,
    brand: BrandSlug = None,
    tag_id: TagId = None,
    group: Annotated[
        str | None,
        Field(min_length=2, description="Only this group, in full, e.g. 'رنگ' (color)."),
    ] = None,
) -> dict[str, Any]:
    """List the filters of a category, brand or tag page with their ids, and its price range.

    Use before mk_browse; options map filter id -> name. Non-brand groups are cut to 40
    (`omitted` = rest): pass `group` for all. max_price in Toman.
    """
    if sum(v is not None for v in (category_id, brand, tag_id)) != 1:
        raise ApiError("Pass exactly one of category_id, brand or tag_id.")
    # Any slug works: the site redirects to the canonical one.
    path = (
        f"/categories/{category_id}/products/x" if category_id else f"/brand/{brand}" if brand else f"/tag/{tag_id}/x"
    )
    url, doc = await get_page(path)
    raw = _first(r"filter_obj = JSON\.parse\('(.*?)'\);", doc)
    if raw is None:
        raise ApiError(f"No product listing at {url}. Check the id or slug with mk_categories / mk_brands.")
    filters, groups = [], json.loads(raw)
    for g in groups:
        if group and _norm(group) not in _norm(g.get("name") or ""):
            continue
        options = [(f.get("filter_id"), (f.get("name") or "").strip()) for f in g.get("filter") or []]
        cut = len(options) if group or g.get("name") == "برند" else 40  # colors can run to 200+ entries
        filters.append(
            {
                "group": g.get("name"),
                "options": dict(options[:cut]),
                **({"omitted": len(options) - cut} if len(options) > cut else {}),
            }
        )
    if group and not filters:
        raise ApiError(
            f"No filter group matching '{group}'. Groups here: {', '.join(g.get('name') or '' for g in groups)}"
        )
    max_price = _first(r"sliderMaxValue:\s*([\d.]+)", doc)
    return {
        "title": _text(_first(r"<h1[^>]*>(.*?)</h1>", doc)) or None,
        "url": url,
        "max_price": int(float(max_price)) if max_price else None,
        "filters": filters,
    }


@tool("List categories")
async def mk_categories(
    query: Annotated[
        str | None,
        Field(min_length=2, description="Filter on Persian name or English slug, e.g. 'شارژر'."),
    ] = None,
) -> dict[str, Any]:
    """List MasterKala's product categories with their ids (about 100).

    Use to get a category_id for mk_browse / mk_filters.
    """
    categories = await cached("categories", _all_categories)
    if query:
        q = _norm(query)
        categories = [c for c in categories if q in _norm(c["title"]) or q in c["slug"].lower()]
    return {"categories": categories}


@tool("List brands")
async def mk_brands(
    query: Annotated[
        str | None,
        Field(min_length=2, description="Filter on brand name, English, e.g. 'xiaomi'."),
    ] = None,
) -> dict[str, Any]:
    """List the brands MasterKala sells with their slugs (about 135).

    Use to get the brand slug for mk_browse / mk_filters.
    """
    brands = await cached("brands", _all_brands)
    if query:
        q = _norm(query)
        brands = [b for b in brands if q in _norm(b["name"]) or q in b["slug"].lower()]
    return {"brands": brands}


@tool("Current deals")
async def mk_deals(
    limit: Annotated[int, Field(ge=1, le=100, description="Max deals.")] = 30,
) -> dict[str, Any]:
    """List products on MasterKala's discount page, biggest discount first.

    ends_in_seconds = time left in the current offer period.
    """
    _, doc = await get_page("/offer")
    timer = _first(r"countdown:\s*\{\s*timer:\s*(\d+)", doc)
    deals = sorted(_cards(doc), key=lambda c: -c["discount_pct"])
    return {"ends_in_seconds": int(timer) if timer else None, "count": len(deals), "deals": deals[:limit]}


async def _all_categories() -> list[dict[str, Any]]:
    _, doc = await get_page("/categories")
    seen: dict[str, dict[str, Any]] = {}
    for cid, slug, label in re.findall(
        r'href="(?:https://masterkala\.com)?/categories/(\d+)/products/([^"]*)"[^>]*>(.*?)</a>', doc, re.S
    ):
        title = _text(label)
        if title and cid not in seen:
            seen[cid] = {"id": int(cid), "title": title, "slug": slug}
    return list(seen.values())


async def _all_brands() -> list[dict[str, str]]:
    _, doc = await get_page("/brand")
    seen: dict[str, str] = {}
    for slug, label in re.findall(r'href="(?:https://masterkala\.com)?/brand/([^"/?#]+)"[^>]*>(.*?)</a>', doc, re.S):
        if _text(label) and slug not in seen:
            seen[slug] = _text(label)
    return [{"slug": s, "name": n} for s, n in seen.items()]


async def _search(query: str, offset: int, limit: int) -> dict[str, Any]:
    data = await api(
        "product/searchproduct", {"v": "1.2", "query": query.strip(), "from": offset, "limit": limit, "filter": ""}
    )
    return data if isinstance(data, dict) else {}


def _search_product(p: dict[str, Any]) -> dict[str, Any]:
    price, final = _toman(p.get("price")), _toman(p.get("pricewithdiscount"))
    label = p.get("top_label")
    pct = int(p.get("percent") or 0)
    if final and price and final >= price:  # no offer: the site shows only final_price
        price, pct = final, 0
    status = (p.get("stock_status") or "").strip()
    out = {
        "id": int(p["product_id"]),
        "title": (p.get("name") or "").strip(),
        "final_price": final,
        "price": price,
        "discount_pct": pct,
        "in_stock": p.get("quantity") == "1",
        "stock_status": None if status == IN_STOCK_TEXT else status,
        "label": label.get("title") if isinstance(label, dict) else None,
        "low_stock": p.get("hint") or None,
        "image": p.get("image") or None,
        "url": f"{BASE}/product/{p['product_id']}/{p.get('slug') or 'x'}",
    }
    return {k: v for k, v in out.items() if k in ("final_price", "price") or v not in (None, "")}


def _cards(doc: str) -> list[dict[str, Any]]:
    """Product cards of a listing page or fragment. Prices on cards are Toman."""
    parts = re.split(
        r'<a href="https://masterkala\.com/product/(\d+)/([^"]*)"[^>]*?class="product-cart-box([^"]*)"', doc
    )
    cards = []
    for i in range(1, len(parts) - 3, 4):
        pid, slug, cls, body = parts[i : i + 4]
        body = body.split("</a>", 1)[0]
        final, old = _first(r'font-bold"[^>]*>([\d,]+)<', body), _first(r"line-through[^>]*>([\d,]+)<", body)
        final_price = int(final.replace(",", "")) if final else None
        pct = _first(r">\s*(\d{1,2})٪\s*<", body)
        badges = [_text(b) for b in re.findall(r'class="tag-badge[^"]*"[^>]*>(.*?)</span>', body, re.S)]
        cards.append(
            {
                "id": int(pid),
                "title": _text(_first(r"product-card-name[^>]*>(.*?)</div>", body)),
                "final_price": final_price,
                "price": int(old.replace(",", "")) if old else final_price,
                "discount_pct": int(pct) if pct else 0,
                "in_stock": "out-of-stock" not in cls and final_price is not None,
                **({"badges": badges} if badges else {}),
                "image": _first(r'<img src="(https://[^"]+)"', body),
                "url": f"{BASE}/product/{pid}/{slug}",
            }
        )
    return cards


def _toman(value: Any) -> int | None:
    """API prices are Toman strings like '4508000.0000'; 0 means no price (not sold online)."""
    n = int(float(value or 0))
    return n or None


def _link_id(link: Any) -> int | None:
    m = re.search(r"/categories/(\d+)/", link or "")
    return int(m.group(1)) if m else None


def _first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.S)
    return m.group(1) if m else None


def _text(fragment: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def _norm(s: str) -> str:
    """Match Persian text loosely: Arabic ي/ك as Persian, half-space as space, case-insensitive."""
    return re.sub(r"\s+", " ", s.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")).strip().lower()
