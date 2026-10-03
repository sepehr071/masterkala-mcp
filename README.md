<!-- mcp-name: io.github.sepehr071/masterkala-mcp -->

<div align="center">

# 🎧 masterkala-mcp

**Let your AI agent shop for gadgets on MasterKala.**<br>
Search earbuds, chargers, power banks and smart watches, compare real prices and specs,<br>
read reviews, check stock and delivery dates, and catch today's discounts, all from Claude, Cursor or Copilot.

[![PyPI](https://img.shields.io/pypi/v/masterkala-mcp?color=2563eb)](https://pypi.org/project/masterkala-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/masterkala-mcp)](https://pypi.org/project/masterkala-mcp/)
[![CI](https://github.com/sepehr071/masterkala-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/sepehr071/masterkala-mcp/actions/workflows/ci.yml)
[![MCP Registry](https://img.shields.io/badge/MCP_Registry-io.github.sepehr071%2Fmasterkala--mcp-7c3aed)](https://registry.modelcontextprotocol.io/v0/servers?search=masterkala-mcp)
[![License: MIT](https://img.shields.io/badge/license-MIT-16a34a)](https://github.com/sepehr071/masterkala-mcp/blob/main/LICENSE)

[![Install in Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](https://cursor.com/en/install-mcp?name=masterkala&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJtYXN0ZXJrYWxhLW1jcCJdfQ==)
[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_masterkala--mcp-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vscode.dev/redirect/mcp/install?name=masterkala&config=%7B%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22masterkala-mcp%22%5D%7D)

[Quick start](#quick-start) · [What it can do](#what-it-can-do) · [Tools](#tools) · [FAQ](#faq) · [فارسی](#فارسی)

</div>

---

## Why

MasterKala lists thousands of accessories, and a search for "power bank" mixes real power banks with
silicone covers, out-of-stock items and things sold only in its shops. Finding *the cheapest one you can
actually order, and what it costs delivered*, means paging through results and opening product pages.
An agent with `masterkala-mcp` does that in seconds:

> **You:** Cheapest Xiaomi power bank I can order now, delivered in Tehran?
>
> **Agent:** *calls* `mk_find_cheapest(query="پاوربانک شیائومی")` → `mk_shipping(product_id=26935)`
>
> | Total | Product | Price | Shipping |
> |---:|---|---:|---|
> | **4,338,000** | پاوربانک 10000 شیائومی گلوریمی Glorimi LightCore 22.5W | 4,188,000 (5% off) | 150,000, Saturday 15:00-18:00 |
> | **5,291,000** | پاوربانک فوق نازک مگنتی 5000 Glorimi FitCore Mag 20W | 5,291,000 (4% off) | free (over 5M) |
> | **5,401,000** | پاوربانک 20000 شیائومی گلوریمی Glorimi LightCore 22.5W | 5,401,000 (6% off) | free (over 5M) |
>
> The 10,000 mAh LightCore is cheapest even with the 150,000 courier fee. The 20,000 mAh LightCore ships
> free and costs 1,063,000 more for twice the capacity. Want me to compare their specs with `mk_specs`?

<sub>Real tool output from 2026-10-03; prices change all the time. Prices are in Toman.</sub>

## What it can do

- 🔎 **Search** products by name in Persian or English, with price, discount and stock
- 💸 **Find the cheapest** in-stock match, with cases and covers filtered out
- 🗂️ **Browse** any category, brand or tag sorted by price, stock or date, with price range and brand/color filters
- 📋 **Read** full product details: colors, stock count, specs, side-by-side comparison, reviews
- 🚚 **Check delivery**: next Tehran courier slot, post to other cities, shipping fee, same-day cut-off
- ⚡ **Catch deals** on the discount page, plus buying guides from the MasterKala blog
- 🔒 **Read-only by design**: no login, no cart, no orders, no reviews posted

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). No API key or account.

<details open>
<summary><b>Claude Code</b></summary>

```bash
claude mcp add masterkala -- uvx masterkala-mcp
```
</details>

<details>
<summary><b>Claude Desktop</b></summary>

Settings → Developer → Edit Config, then add:

```json
{
  "mcpServers": {
    "masterkala": { "command": "uvx", "args": ["masterkala-mcp"] }
  }
}
```
</details>

<details>
<summary><b>Cursor</b></summary>

Click **Install in Cursor** above, or add the Claude Desktop block to `~/.cursor/mcp.json`.
</details>

<details>
<summary><b>VS Code (Copilot agent mode)</b></summary>

Click **Install in VS Code** above, or add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "masterkala": { "type": "stdio", "command": "uvx", "args": ["masterkala-mcp"] }
  }
}
```
</details>

<details>
<summary><b>Anything else</b></summary>

It's a standard stdio MCP server: run `uvx masterkala-mcp`, or `pip install masterkala-mcp` and run `masterkala-mcp`.
</details>

Then just ask:

- "Cheapest Bluetooth earbuds between 3 and 5 million Toman, and which one has the best reviews?"
- "Compare the specs of the Green Lion Ocean and the Awei T66."
- "Is the blue CMF Buds Pro 2 in stock? When would it reach Tehran?"
- <span dir="rtl">بهترین تخفیف&zwnj;های امروز مسترکالا روی پاوربانک چیه؟</span>

## How it works

```text
  AI agent  (Claude, Cursor, Copilot, ...)
      │
      │  MCP over stdio
      ▼
  masterkala-mcp  (runs on your machine)
      │
      │  HTTPS
      └──────▶  masterkala.com   JSON API, listing fragments, product pages
```

`masterkala-mcp` runs locally and calls the same public endpoints the masterkala.com website uses.
There's no hosted server in between, no API key, and nothing about you is sent anywhere else.

## Tools

<details open>
<summary><b>🔎 Find products</b> (7)</summary>

| Tool | What it does |
|---|---|
| `mk_search` | Search by keyword: price, discount, stock, plus matching categories and tag pages |
| `mk_find_cheapest` | Cheapest in-stock matches for a keyword, one flat list (accessories filtered out) |
| `mk_browse` | A category, brand or tag sorted by price / stock / date, with price range and filters |
| `mk_filters` | Brand, color and feature filter ids and the price range of a category, brand or tag |
| `mk_categories` | Product categories and their ids |
| `mk_brands` | Brands and their slugs |
| `mk_deals` | Everything on the discount page, biggest discount first, with the time left |
</details>

<details open>
<summary><b>📦 One product</b> (5)</summary>

| Tool | What it does |
|---|---|
| `mk_product` | Price, discount, stock status and count, colors, brand, category, rating, shops that have it |
| `mk_specs` | Specification table of 1-4 products side by side |
| `mk_reviews` | Customer reviews with star breakdown and the store's replies |
| `mk_shipping` | Next delivery slot and fee for Tehran and other cities, same-day cut-off |
| `mk_branches` | MasterKala's physical shops with address, phone and map location |
</details>

<details open>
<summary><b>📝 Blog</b> (2)</summary>

| Tool | What it does |
|---|---|
| `mk_blog_posts` | Buying guides, comparisons and how-tos, newest first |
| `mk_blog_comments` | Readers' questions on a post with the store writer's answers |
</details>

All tools are annotated `readOnlyHint: true` and return compact structured JSON, so they don't flood the agent's context.

## Good to know

- **Prices are in Toman.** `final_price` is what you pay, `price` is before discount, `discount_pct` is a whole percent. The site's structured data is in Rial; the server converts it.
- **Shipping is free from 5,000,000 Toman** per order for most items (bulky goods such as large speakers never ship free; `mk_shipping` gives `free_shipping_from: null` for them); below that, Tehran courier and post were 150,000 / 155,000 Toman on 2026-10-03. There is no address API, so `mk_shipping` estimates for Tehran and "other cities by post".
- **Stock**: `in_stock` means orderable online now. Other statuses: ناموجود (sold out), به زودی (coming soon), موجود در شعب حضوری (only in the physical shops).
- **Ratings are 1–5**, `null` when nobody has reviewed the product yet.
- **Persian queries match best** (`هندزفری`, `پاوربانک`), but English brand and model names work too (`xiaomi`, `Buds Pro`).

## FAQ

<details>
<summary><b>Can it place an order for me?</b></summary>

No, and that's deliberate. It has no login and never touches the cart, order, payment, wishlist or review endpoints.
The agent finds the best option; you buy it on masterkala.com.
</details>

<details>
<summary><b>Why does <code>mk_find_cheapest</code> skip some items?</b></summary>

It keeps only items you can order online now, whose title contains every word of your query, and drops cases,
covers and screen protectors unless you ask for them (`include_accessories: true`, or a query like "کاور ...").
It scans the first 500 results by default (in-stock items come first); `complete: false` in the reply means more
in-stock items lie past that, so raise `scan` (up to 1500). `mk_search` shows everything.
</details>

<details>
<summary><b>I get "Could not reach masterkala.com"</b></summary>

The server retries a dropped connection once. If it still fails, check your internet connection. System proxy
variables are ignored on purpose; set `MASTERKALA_MCP_PROXY` if you need a proxy.
</details>

<details>
<summary><b>Claude Desktop says <code>uvx</code> is not found</b></summary>

Use the full path to `uvx` (`where uvx` on Windows, `which uvx` on macOS/Linux) as `command`.
</details>

<details>
<summary><b>How do I debug what the agent sees?</b></summary>

```bash
npx @modelcontextprotocol/inspector uvx masterkala-mcp
```
</details>

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MASTERKALA_MCP_PROXY` | unset | HTTP proxy for every request, e.g. `http://user:pass@host:port` |

## فارسی

<div dir="rtl">

**masterkala-mcp** به دستیار هوش مصنوعی شما (Claude، Cursor، Copilot و ...) اجازه می&zwnj;دهد در مسترکالا جستجو کند،
ارزان&zwnj;ترین کالای موجود را پیدا کند، مشخصات و نظرات را مقایسه کند و زمان و هزینه ارسال و تخفیف&zwnj;های روز را ببیند.

- فقط خواندنی است: وارد حساب نمی&zwnj;شود، سبد خرید نمی&zwnj;سازد، سفارش ثبت نمی&zwnj;کند و نظر نمی&zwnj;فرستد.
- قیمت&zwnj;ها به تومان است و کاور و قاب را از نتایج «ارزان&zwnj;ترین» جدا می&zwnj;کند.
- روی سیستم خود شما اجرا می&zwnj;شود و به هیچ سرور واسطی داده نمی&zwnj;فرستد.

**نصب در Claude Code:**

</div>

```bash
claude mcp add masterkala -- uvx masterkala-mcp
```

<div dir="rtl">

بعد بپرسید: «ارزان&zwnj;ترین هندزفری بلوتوث بین ۳ تا ۵ میلیون تومان کدام است و کی به تهران می&zwnj;رسد؟»

</div>

## Development

```bash
git clone https://github.com/sepehr071/masterkala-mcp && cd masterkala-mcp
uv sync
uv run pytest            # offline, against recorded responses
uv run pytest -m live    # real masterkala.com
uv run ruff check .
```

Tools live in `src/masterkala_mcp/catalog.py`, `product.py` and `blog.py`; each is a typed async function with a
docstring that tells the agent when to use it. Issues and PRs are welcome, especially new tools and fixes for site changes.

Releases: bump the version in `pyproject.toml` and `server.json`, then push a `v*` tag. GitHub Actions tests,
publishes to PyPI and the [MCP Registry](https://registry.modelcontextprotocol.io), and creates the GitHub Release.

## Disclaimer

Unofficial and not affiliated with or endorsed by MasterKala. It uses the public endpoints of the masterkala.com
website, which can change without notice. Please keep request rates reasonable.

## License

[MIT](https://github.com/sepehr071/masterkala-mcp/blob/main/LICENSE)
