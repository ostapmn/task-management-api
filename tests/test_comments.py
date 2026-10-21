async def test_comments_create_and_list(client, alice, bob):
    aid, ah = alice
    bid, bh = bob
    tid = (await client.post("/tasks", json={"title": "t"}, headers=ah)).json()["id"]

    r1 = await client.post(f"/tasks/{tid}/comments", json={"text": "first"}, headers=ah)
    r2 = await client.post(f"/tasks/{tid}/comments", json={"text": "second"}, headers=bh)
    assert r1.status_code == r2.status_code == 201
    assert r2.json()["author_id"] == bid and r2.json()["task_id"] == tid

    listed = await client.get(f"/tasks/{tid}/comments", headers=ah)
    assert [c["text"] for c in listed.json()] == ["first", "second"]


async def test_comment_errors(client, alice):
    _, h = alice
    assert (await client.post("/tasks/999/comments", json={"text": "x"}, headers=h)).status_code == 404
    assert (await client.get("/tasks/999/comments", headers=h)).status_code == 404
    tid = (await client.post("/tasks", json={"title": "t"}, headers=h)).json()["id"]
    assert (await client.post(f"/tasks/{tid}/comments", json={"text": ""}, headers=h)).status_code == 422
    assert (await client.get(f"/tasks/{tid}/comments")).status_code == 401


async def test_comments_deleted_with_task(client, alice, session_factory):
    from sqlalchemy import func, select

    from app.models import Comment

    _, h = alice
    tid = (await client.post("/tasks", json={"title": "t"}, headers=h)).json()["id"]
    await client.post(f"/tasks/{tid}/comments", json={"text": "x"}, headers=h)
    assert (await client.delete(f"/tasks/{tid}", headers=h)).status_code == 204
    async with session_factory() as s:
        assert await s.scalar(select(func.count()).select_from(Comment)) == 0
