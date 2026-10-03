"""MasterKala blog: buying guides, comparisons, how-tos, and the Q&A in their comments."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from .http import BASE, api
from .registry import tool

BLOG_CATEGORIES = {
    "buying_guide": 63,
    "comparison_review": 68,
    "how_to": 65,
    "tips": 69,
    "best_of": 1,
    "introduction": 67,
    "news": 64,
    "apps_games": 66,
    "learn_more": 71,
    "announcement": 70,
}


@tool("Blog posts and buying guides")
async def mk_blog_posts(
    category: Annotated[
        Literal[
            "all",
            "buying_guide",
            "comparison_review",
            "how_to",
            "tips",
            "best_of",
            "introduction",
            "news",
            "apps_games",
            "learn_more",
            "announcement",
        ],
        Field(description="Blog section, e.g. 'buying_guide' (راهنمای خرید) or 'comparison_review' (مقایسه و بررسی)."),
    ] = "buying_guide",
    page: Annotated[int, Field(ge=0, le=200, description="Page number, from 0, newest first.")] = 0,
    limit: Annotated[int, Field(ge=1, le=50, description="Posts per page.")] = 10,
) -> dict[str, Any]:
    """List MasterKala blog posts (buying guides, comparisons, how-tos), newest first, with links.

    Use when the user asks which product type to choose or how to use a gadget: point them to
    the matching guide. Readers' questions answered by the store: mk_blog_comments.
    """
    body: dict[str, Any] = {"from": page * limit, "limit": str(limit)}
    if category != "all":
        body["cat"] = str(BLOG_CATEGORIES[category])
    data = await api("blog/getall", body)
    return {
        "total": int(data.get("count") or 0),
        "page": page,
        "posts": [
            {
                "id": int(p["post_id"]),
                "title": p.get("title"),
                "category": p.get("category_name"),
                "date": (p.get("date_published") or "")[:10] or None,
                "read_minutes": int(p.get("read_time") or 0) or None,
                "url": f"{BASE}/post/{p['post_id']}/{p.get('slug') or 'x'}",
            }
            for p in data.get("list") or []
        ],
    }


@tool("Blog post comments")
async def mk_blog_comments(
    post_id: Annotated[int, Field(ge=1, le=1_000_000, description="Blog post id from mk_blog_posts, e.g. 330.")],
    limit: Annotated[int, Field(ge=1, le=20, description="Max comment threads to return, newest first.")] = 10,
) -> dict[str, Any]:
    """Read the comments of a blog post as threads, with the store writer's answers as replies.

    Useful as a support FAQ: many posts hold readers' product questions answered by MasterKala.
    """
    # Send only post_id: the same route posts a comment when it gets a `data` object.
    data = await api("blog/getpostreviews", {"post_id": str(post_id)})
    comments = data.get("list") or []
    threads: list[dict[str, Any]] = []
    thread_of: dict[str, dict[str, Any]] = {}  # comment id -> its top-level thread
    for c in reversed(comments):  # oldest first, so a parent exists before its replies
        item = {
            "author": (c.get("author") or "").strip(),
            "date": c.get("date_added"),
            "text": (c.get("description") or "").strip(),
        }
        thread = thread_of.get(c.get("reply_to_review_id") or "0")
        if thread is not None:
            thread["replies"].append(item)
        else:
            thread = {**item, "replies": []}
            threads.append(thread)
        thread_of[c["review_id"]] = thread
    return {"count": len(comments), "threads": threads[::-1][:limit]}
