"""MCP server entry point: registers every read-only MasterKala tool."""

import logging

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from . import __version__, blog, catalog, product  # noqa: F401  (imports register the tools)
from .registry import TOOLS

INSTRUCTIONS = """\
Unofficial, read-only access to MasterKala (masterkala.com), an Iranian online shop for mobile
accessories and gadgets: earbuds, chargers, cables, power banks, smart watches, speakers, small
appliances. MasterKala sells its own stock (no third-party sellers). Nothing here can log in, add
to a cart, order or post reviews.

Workflow:
1. Find products: mk_search (keyword, prices, stock; also returns category ids) or
   mk_find_cheapest (cheapest in-stock matches, one flat list).
2. Browse with sort / price range / filters: mk_browse with a category_id (mk_categories),
   brand slug (mk_brands) or tag_id; brand/color/feature filter ids from mk_filters. For a
   keyword use mk_search / mk_find_cheapest (the site ignores sort on keyword listings).
3. One product: mk_product (price, stock count, colors, branches), mk_specs (specs, compare up
   to 4), mk_reviews, mk_shipping (delivery date and fee).
4. Deals: mk_deals. Buying guides: mk_blog_posts, then mk_blog_comments for readers' Q&A.
   Buy in person: mk_branches (Tehran shops).

Conventions: all prices are Toman (the site's JSON-LD is Rial; it is converted). final_price is
what the customer pays, price is before discount, discount_pct is an int. Ratings are 1-5, null
when there are no reviews. Product ids are numbers like 24855. Persian queries match best
('هندزفری', 'پاوربانک'), English brand/model names also work. There is no location API: shipping
estimates are for Tehran (courier) and other cities (post); shipping is free from 5,000,000 Toman
for most items, bulky ones never ship free (mk_shipping gives the exact rule per product).
True cost = sum(final_price x qty) + shipping fee (0 above the product's free_shipping_from).
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)

mcp = MCPServer(
    "masterkala-mcp",
    title="MasterKala",
    instructions=INSTRUCTIONS,
    version=__version__,
    website_url="https://github.com/sepehr071/masterkala-mcp",
)

for fn, title in TOOLS:
    mcp.add_tool(fn, title=title, annotations=READ_ONLY)


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per request floods client logs
    mcp.run()


if __name__ == "__main__":
    main()
