import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.live]


async def call(client, name, args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def test_mk_blog_posts(client):
    data = await call(client, "mk_blog_posts", {"category": "buying_guide", "limit": 3})
    assert (
        data["total"] > 50
        and len(data["posts"]) == 3
        and data["posts"][0]["url"].startswith("https://masterkala.com/post/")
    )


async def test_mk_blog_comments(client):
    data = await call(client, "mk_blog_comments", {"post_id": 676})
    assert data["count"] >= 10 and data["threads"][0]["text"]
