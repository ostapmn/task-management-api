from tests.conftest import future


async def test_crud(client, alice):
    uid, h = alice
    r = await client.post(
        "/tasks",
        json={"title": "Write docs", "description": "readme", "priority": "High", "assignee_id": uid, "deadline": future()},
        headers=h,
    )
    assert r.status_code == 201
    task = r.json()
    assert task["status"] == "Backlog" and task["author_id"] == uid and task["priority"] == "High"
    assert task["created_at"] and task["updated_at"]

    got = await client.get(f"/tasks/{task['id']}", headers=h)
    assert got.status_code == 200 and got.json()["title"] == "Write docs"

    upd = await client.patch(f"/tasks/{task['id']}", json={"title": "Write better docs", "priority": "Low"}, headers=h)
    assert upd.status_code == 200
    assert upd.json()["title"] == "Write better docs" and upd.json()["priority"] == "Low"
    assert upd.json()["description"] == "readme"

    assert (await client.delete(f"/tasks/{task['id']}", headers=h)).status_code == 204


async def test_can_unassign_with_null(client, alice):
    uid, h = alice
    r = await client.post("/tasks", json={"title": "t", "assignee_id": uid}, headers=h)
    upd = await client.patch(f"/tasks/{r.json()['id']}", json={"assignee_id": None}, headers=h)
    assert upd.status_code == 200 and upd.json()["assignee_id"] is None


async def test_validation(client, alice):
    _, h = alice
    assert (await client.post("/tasks", json={"title": ""}, headers=h)).status_code == 422
    assert (await client.post("/tasks", json={"title": "x", "priority": "Urgent"}, headers=h)).status_code == 422
    assert (await client.patch("/tasks/1/status", json={"status": "Nope"}, headers=h)).status_code == 422


async def test_not_found(client, alice):
    _, h = alice
    assert (await client.get("/tasks/999", headers=h)).status_code == 404
    assert (await client.patch("/tasks/999", json={"title": "x"}, headers=h)).status_code == 404
    assert (await client.delete("/tasks/999", headers=h)).status_code == 404


async def test_permissions(client, alice, bob, make_user):
    aid, ah = alice
    bid, bh = bob
    _, ch = await make_user("carol@example.com")
    tid = (await client.post("/tasks", json={"title": "t", "assignee_id": bid}, headers=ah)).json()["id"]

    # only the author edits / deletes
    assert (await client.patch(f"/tasks/{tid}", json={"title": "x"}, headers=bh)).status_code == 403
    assert (await client.delete(f"/tasks/{tid}", headers=bh)).status_code == 403
    # author or assignee may change status; strangers may not
    assert (await client.patch(f"/tasks/{tid}/status", json={"status": "In Progress"}, headers=ch)).status_code == 403
    assert (await client.patch(f"/tasks/{tid}/status", json={"status": "In Progress"}, headers=bh)).status_code == 200
    assert (await client.patch(f"/tasks/{tid}/status", json={"status": "Review"}, headers=ah)).status_code == 200
    # everyone can read
    assert (await client.get(f"/tasks/{tid}", headers=ch)).status_code == 200


async def test_updated_at_changes(client, alice):
    _, h = alice
    t = (await client.post("/tasks", json={"title": "t"}, headers=h)).json()
    upd = (await client.patch(f"/tasks/{t['id']}", json={"title": "u"}, headers=h)).json()
    assert upd["updated_at"] > t["updated_at"]
    assert upd["created_at"] == t["created_at"]


async def test_naive_datetimes_are_treated_as_utc(client, alice):
    _, h = alice
    r = await client.post("/tasks", json={"title": "t", "deadline": "2030-01-01T10:00:00"}, headers=h)
    assert r.status_code == 201
    assert r.json()["deadline"].startswith("2030-01-01T10:00:00")
    tid = r.json()["id"]
    assert (await client.patch(f"/tasks/{tid}", json={"deadline": "2031-01-01T10:00:00"}, headers=h)).status_code == 200
    r = await client.get("/tasks?deadline_from=2029-01-01T00:00:00&deadline_to=2030-06-01T00:00:00", headers=h)
    assert r.status_code == 200 and r.json()["total"] == 0  # deadline moved to 2031
    assert (await client.get("/tasks?deadline_from=2030-01-01T00:00:00", headers=h)).status_code == 200


async def test_concurrent_assignment_respects_limit(client, alice):
    import asyncio

    uid, h = alice
    for _ in range(9):
        assert (await client.post("/tasks", json={"title": "t", "assignee_id": uid}, headers=h)).status_code == 201
    results = await asyncio.gather(
        *[client.post("/tasks", json={"title": "race", "assignee_id": uid}, headers=h) for _ in range(5)]
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409, 409, 409]
