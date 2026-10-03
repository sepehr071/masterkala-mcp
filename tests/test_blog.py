import pytest
from conftest import fixture

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
