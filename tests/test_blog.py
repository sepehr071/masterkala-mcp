import pytest
from conftest import fixture
from mcp import Client

from masterkala_mcp.server import mcp

pytestmark = pytest.mark.anyio


async def test_mk_blog_posts(client, api):
    api["blog/getall"] = fixture("blog_posts.json")
    out = (
        await client.call_tool("mk_blog_posts", {"category": "buying_guide", "page": 1, "limit": 3})
    ).structured_content
    assert out["total"] == 114
    assert out["posts"][0] == {
        "id": 931,
        "title": "راهنمای جامع خرید هواپز: چه مدل ایرفرایری برای شما مناسب است؟",
        "category": "راهنمای خرید",
        "date": "2026-09-27",
        "read_minutes": 33,
        "url": "https://masterkala.com/post/931/air-fryer-buying-guide",
    }
    assert api.body() == {"from": 3, "limit": "3", "cat": "63"}


async def test_mk_blog_posts_all(client, api):
    api["blog/getall"] = fixture("blog_posts.json")
    await client.call_tool("mk_blog_posts", {"category": "all"})
    assert "cat" not in api.body()


async def test_mk_blog_comments_threads(client, api):
    api["blog/getpostreviews"] = fixture("blog_comments.json")
    out = (await client.call_tool("mk_blog_comments", {"post_id": 676, "limit": 3})).structured_content
    assert out["count"] == 10
    assert [t["author"] for t in out["threads"]] == ["مریم", "بهار", "محبوب"]
    assert out["threads"][1]["replies"] == [
        {"author": "نویسنده مسترکالا", "date": "2026-06-20 13:09:27", "text": "سلام، ممنون از توجه شما."}
    ]
    # read-only: only post_id, never a `data` object
    assert api.body() == {"post_id": "676"}


async def test_blog_comments_text_and_replies_are_capped(client, api):
    long = "x" * 1000
    rows = [{"review_id": "1", "reply_to_review_id": "0", "author": "a", "date_added": "d", "description": long}] + [
        {"review_id": str(i), "reply_to_review_id": "1", "author": "s", "date_added": "d", "description": "r"}
        for i in range(2, 8)
    ]
    api["blog/getpostreviews"] = {"list": rows[::-1], "success": "1"}
    thread = (await client.call_tool("mk_blog_comments", {"post_id": 1})).structured_content["threads"][0]
    assert len(thread["text"]) < 450 and thread["text"].endswith("[truncated]")
    assert len(thread["replies"]) == 3 and thread["more_replies"] == 3


async def test_result_is_one_compact_text_block(api):
    api["blog/getall"] = fixture("blog_posts.json")
    async with Client(mcp) as raw:  # the real client, without the conftest `client` shim
        result = await raw.call_tool("mk_blog_posts", {"limit": 1})
        assert len(result.content) == 1 and result.structured_content is None
        assert "\n" not in result.content[0].text and '": ' not in result.content[0].text
        assert all(t.output_schema is None for t in (await raw.list_tools()).tools)


async def test_blog_comments_full_text(client, api):
    rows = [
        {"review_id": "1", "reply_to_review_id": "0", "author": "a", "date_added": "d", "description": "x" * 1000}
    ] + [
        {"review_id": str(i), "reply_to_review_id": "1", "author": "s", "date_added": "d", "description": "r"}
        for i in range(2, 8)
    ]
    api["blog/getpostreviews"] = {"list": rows[::-1], "success": "1"}
    thread = (await client.call_tool("mk_blog_comments", {"post_id": 1, "full_text": True})).structured_content[
        "threads"
    ][0]
    assert thread["text"] == "x" * 1000 and len(thread["replies"]) == 6 and "more_replies" not in thread
