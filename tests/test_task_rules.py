import pytest

from tests.conftest import future, past


async def _task(client, headers, **body):
    r = await client.post("/tasks", json={"title": "t", **body}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _set(client, headers, task_id, status):
    return await client.patch(f"/tasks/{task_id}/status", json={"status": status}, headers=headers)


async def test_full_happy_path(client, alice):
    uid, h = alice
    tid = await _task(client, h, assignee_id=uid, deadline=future())
    for s in ("In Progress", "Review", "Done"):
        r = await _set(client, h, tid, s)
        assert r.status_code == 200 and r.json()["status"] == s


@pytest.mark.parametrize(
    "path",
    [
        ["Review"],  # Backlog -> Review
        ["Done"],  # Backlog -> Done
        ["In Progress", "Backlog"],  # revert
        ["In Progress", "Review", "In Progress"],  # revert
        ["In Progress", "Done"],  # skip Review
        ["Cancelled", "Backlog"],  # leave final
        ["Cancelled", "In Progress"],
    ],
)
async def test_invalid_transitions(client, alice, path):
    uid, h = alice
    tid = await _task(client, h, assignee_id=uid)
    for s in path[:-1]:
        assert (await _set(client, h, tid, s)).status_code == 200
    assert (await _set(client, h, tid, path[-1])).status_code == 409


async def test_cancel_allowed_from_backlog_and_in_progress_only(client, alice):
    uid, h = alice
    t1 = await _task(client, h)
    assert (await _set(client, h, t1, "Cancelled")).status_code == 200
    t2 = await _task(client, h)
    await _set(client, h, t2, "In Progress")
    assert (await _set(client, h, t2, "Cancelled")).status_code == 200
    t3 = await _task(client, h)
    await _set(client, h, t3, "In Progress")
    await _set(client, h, t3, "Review")
    assert (await _set(client, h, t3, "Cancelled")).status_code == 409


async def test_done_requires_assignee(client, alice):
    _, h = alice
    tid = await _task(client, h)
    await _set(client, h, tid, "In Progress")
    await _set(client, h, tid, "Review")
    r = await _set(client, h, tid, "Done")
    assert r.status_code == 409 and "assignee" in r.json()["detail"]


async def test_done_blocked_after_deadline(client, alice, insert_task):
    uid, h = alice
    tid = await insert_task(uid, assignee_id=uid, status="Review", deadline=past())
    r = await _set(client, h, tid, "Done")
    assert r.status_code == 409 and "deadline" in r.json()["detail"]


async def test_done_allowed_without_deadline(client, alice):
    uid, h = alice
    tid = await _task(client, h, assignee_id=uid)
    for s in ("In Progress", "Review", "Done"):
        assert (await _set(client, h, tid, s)).status_code == 200


async def test_past_deadline_rejected_on_create_and_update(client, alice):
    uid, h = alice
    r = await client.post("/tasks", json={"title": "t", "deadline": past().isoformat()}, headers=h)
    assert r.status_code == 422
    tid = await _task(client, h)
    r = await client.patch(f"/tasks/{tid}", json={"deadline": past().isoformat()}, headers=h)
    assert r.status_code == 422


async def test_old_task_with_past_deadline_still_editable_when_deadline_untouched(client, alice, insert_task):
    uid, h = alice
    tid = await insert_task(uid, deadline=past())
    r = await client.patch(f"/tasks/{tid}", json={"title": "renamed"}, headers=h)
    assert r.status_code == 200 and r.json()["title"] == "renamed"


async def test_assignee_locked_in_review(client, alice, bob):
    uid, h = alice
    bid, _ = bob
    tid = await _task(client, h, assignee_id=uid)
    await _set(client, h, tid, "In Progress")
    # still changeable while In Progress
    assert (await client.patch(f"/tasks/{tid}", json={"assignee_id": bid}, headers=h)).status_code == 200
    await _set(client, h, tid, "Review")
    r = await client.patch(f"/tasks/{tid}", json={"assignee_id": uid}, headers=h)
    assert r.status_code == 409
    # other fields remain editable in Review
    assert (await client.patch(f"/tasks/{tid}", json={"title": "new"}, headers=h)).status_code == 200


@pytest.mark.parametrize("final", ["Done", "Cancelled"])
async def test_final_tasks_not_editable(client, alice, final):
    uid, h = alice
    tid = await _task(client, h, assignee_id=uid)
    if final == "Done":
        for s in ("In Progress", "Review", "Done"):
            await _set(client, h, tid, s)
    else:
        await _set(client, h, tid, "Cancelled")
    r = await client.patch(f"/tasks/{tid}", json={"title": "x"}, headers=h)
    assert r.status_code == 409


async def test_delete_rules(client, alice):
    uid, h = alice
    in_progress = await _task(client, h)
    await _set(client, h, in_progress, "In Progress")
    assert (await client.delete(f"/tasks/{in_progress}", headers=h)).status_code == 409
    await _set(client, h, in_progress, "Review")
    assert (await client.delete(f"/tasks/{in_progress}", headers=h)).status_code == 409

    backlog = await _task(client, h)
    assert (await client.delete(f"/tasks/{backlog}", headers=h)).status_code == 204
    assert (await client.get(f"/tasks/{backlog}", headers=h)).status_code == 404

    cancelled = await _task(client, h)
    await _set(client, h, cancelled, "Cancelled")
    assert (await client.delete(f"/tasks/{cancelled}", headers=h)).status_code == 204


async def test_active_task_limit(client, alice, bob):
    uid, h = alice
    bid, bh = bob
    ids = [await _task(client, h, assignee_id=uid) for _ in range(10)]
    r = await client.post("/tasks", json={"title": "11th", "assignee_id": uid}, headers=h)
    assert r.status_code == 409

    # reassigning someone else's task onto the full user is also blocked
    other = await _task(client, h, assignee_id=bid)
    assert (await client.patch(f"/tasks/{other}", json={"assignee_id": uid}, headers=h)).status_code == 409

    # unassigned tasks don't count; finishing/cancelling frees a slot
    await _set(client, h, ids[0], "Cancelled")
    assert (await client.patch(f"/tasks/{other}", json={"assignee_id": uid}, headers=h)).status_code == 200


async def test_nonexistent_assignee_rejected(client, alice):
    _, h = alice
    r = await client.post("/tasks", json={"title": "t", "assignee_id": 9999}, headers=h)
    assert r.status_code == 422
