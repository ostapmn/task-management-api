from sqlalchemy import select

from app.models import Task
from app.worker import cancel_overdue
from tests.conftest import future_dt, past


async def test_cancel_overdue_sweep(session_factory, alice, insert_task):
    uid, _ = alice
    overdue_ids = [
        await insert_task(uid, status="Backlog", deadline=past()),
        await insert_task(uid, status="In Progress", deadline=past()),
        await insert_task(uid, status="Review", deadline=past()),  # system action: allowed
    ]
    untouched = {
        await insert_task(uid, status="Done", deadline=past()): "Done",
        await insert_task(uid, status="Cancelled", deadline=past()): "Cancelled",
        await insert_task(uid, status="Backlog", deadline=None): "Backlog",
    }
    fut = await insert_task(uid, status="In Progress", deadline=future_dt())
    untouched[fut] = "In Progress"

    async with session_factory() as s:
        assert await cancel_overdue(s) == 3

    async with session_factory() as s:
        rows = {t.id: t.status.value for t in (await s.scalars(select(Task))).all()}
    assert all(rows[i] == "Cancelled" for i in overdue_ids)
    for task_id, expected in untouched.items():
        assert rows[task_id] == expected

    async with session_factory() as s:
        assert await cancel_overdue(s) == 0  # idempotent


async def test_overdue_endpoint_empty_after_sweep(client, session_factory, alice, insert_task):
    uid, h = alice
    await insert_task(uid, status="Backlog", deadline=past())
    assert (await client.get("/tasks/overdue", headers=h)).json()["total"] == 1
    async with session_factory() as s:
        await cancel_overdue(s)
    assert (await client.get("/tasks/overdue", headers=h)).json()["total"] == 0
