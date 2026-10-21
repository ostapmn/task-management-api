from tests.conftest import future, future_dt, past


async def _mk(client, h, **body):
    r = await client.post("/tasks", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def test_default_order_priority_then_deadline(client, alice):
    _, h = alice
    await _mk(client, h, title="low-soon", priority="Low", deadline=future(1))
    await _mk(client, h, title="high-late", priority="High", deadline=future(5))
    await _mk(client, h, title="high-soon", priority="High", deadline=future(2))
    await _mk(client, h, title="med-none", priority="Medium")
    await _mk(client, h, title="med-soon", priority="Medium", deadline=future(3))
    r = await client.get("/tasks", headers=h)
    assert [t["title"] for t in r.json()["items"]] == [
        "high-soon", "high-late", "med-soon", "med-none", "low-soon",
    ]


async def test_sorting_options(client, alice):
    _, h = alice
    await _mk(client, h, title="a", priority="Low", deadline=future(3))
    await _mk(client, h, title="b", priority="High", deadline=future(1))
    await _mk(client, h, title="c", priority="Medium")

    def titles(r):
        return [t["title"] for t in r.json()["items"]]

    assert titles(await client.get("/tasks?sort_by=created_at&order=desc", headers=h)) == ["c", "b", "a"]
    assert titles(await client.get("/tasks?sort_by=created_at&order=asc", headers=h)) == ["a", "b", "c"]
    assert titles(await client.get("/tasks?sort_by=deadline&order=asc", headers=h)) == ["b", "a", "c"]
    assert titles(await client.get("/tasks?sort_by=deadline&order=desc", headers=h)) == ["a", "b", "c"]
    assert titles(await client.get("/tasks?sort_by=priority&order=asc", headers=h)) == ["a", "c", "b"]
    assert (await client.get("/tasks?sort_by=title", headers=h)).status_code == 422


async def test_search_and_filters(client, alice, bob):
    aid, h = alice
    bid, _ = bob
    await _mk(client, h, title="Fix login bug", description="500 on submit", priority="High", assignee_id=aid, deadline=future(1))
    await _mk(client, h, title="Write docs", description="mentions LOGIN flow", priority="Low", assignee_id=bid, deadline=future(10))
    await _mk(client, h, title="100% done_ish", priority="Medium")

    def titles(r):
        return sorted(t["title"] for t in r.json()["items"])

    assert titles(await client.get("/tasks?q=login", headers=h)) == ["Fix login bug", "Write docs"]
    assert titles(await client.get("/tasks?q=100%25", headers=h)) == ["100% done_ish"]  # % is literal
    assert titles(await client.get("/tasks?q=done_", headers=h)) == ["100% done_ish"]
    assert titles(await client.get("/tasks?q=Fx", headers=h)) == []
    assert titles(await client.get("/tasks?priority=High", headers=h)) == ["Fix login bug"]
    assert titles(await client.get(f"/tasks?assignee_id={bid}", headers=h)) == ["Write docs"]
    assert titles(await client.get("/tasks?status=Backlog", headers=h)) == sorted(
        ["Fix login bug", "Write docs", "100% done_ish"]
    )
    assert titles(await client.get("/tasks?status=Done", headers=h)) == []
    r = await client.get("/tasks", params={"deadline_to": future(5)}, headers=h)
    assert titles(r) == ["Fix login bug"]
    r = await client.get("/tasks", params={"deadline_from": future(5)}, headers=h)
    assert titles(r) == ["Write docs"]


async def test_pagination(client, alice):
    _, h = alice
    for i in range(5):
        await _mk(client, h, title=f"t{i}")
    r = await client.get("/tasks?limit=2&offset=0&sort_by=created_at&order=asc", headers=h)
    body = r.json()
    assert body["total"] == 5 and body["limit"] == 2 and body["offset"] == 0
    assert [t["title"] for t in body["items"]] == ["t0", "t1"]
    r = await client.get("/tasks?limit=2&offset=4&sort_by=created_at&order=asc", headers=h)
    assert [t["title"] for t in r.json()["items"]] == ["t4"]
    assert (await client.get("/tasks?limit=0", headers=h)).status_code == 422
    assert (await client.get("/tasks?limit=101", headers=h)).status_code == 422
    assert (await client.get("/tasks?offset=-1", headers=h)).status_code == 422


async def test_overdue_endpoint_and_route_order(client, alice, insert_task):
    uid, h = alice
    a = await insert_task(uid, title="overdue-backlog", deadline=past(2))
    b = await insert_task(uid, title="overdue-review", status="Review", deadline=past(1))
    await insert_task(uid, title="overdue-done", status="Done", deadline=past(1))
    await insert_task(uid, title="overdue-cancelled", status="Cancelled", deadline=past(1))
    await insert_task(uid, title="future", deadline=future_dt())
    await insert_task(uid, title="no-deadline")
    r = await client.get("/tasks/overdue", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert [t["id"] for t in body["items"]] == [a, b]  # most overdue first


async def test_stats(client, alice, insert_task):
    uid, h = alice
    await insert_task(uid, status="Backlog", priority="High", deadline=past())
    await insert_task(uid, status="Backlog", priority="Low")
    await insert_task(uid, status="In Progress", priority="High")
    await insert_task(uid, status="Review", priority="Medium")
    await insert_task(uid, status="Done", priority="Medium", deadline=past())
    await insert_task(uid, status="Cancelled", priority="Low")
    r = await client.get("/tasks/stats", headers=h)
    assert r.status_code == 200
    s = r.json()
    assert s["total"] == 6
    assert s["by_status"] == {"Backlog": 2, "In Progress": 1, "Review": 1, "Done": 1, "Cancelled": 1}
    assert s["by_priority"] == {"Low": 2, "Medium": 2, "High": 2}
    assert s["overdue"] == 1
    assert s["active"] == 4


async def test_stats_empty(client, alice):
    _, h = alice
    s = (await client.get("/tasks/stats", headers=h)).json()
    assert s["total"] == 0 and s["active"] == 0 and s["overdue"] == 0
    assert all(v == 0 for v in s["by_status"].values())
