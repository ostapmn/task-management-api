from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.models import Priority, Task, TaskStatus
from app.schemas.task import Page, PgId, ensure_aware, StatusChange, TaskCreate, TaskOut, TaskStats, TaskUpdate
from app.services import query as q_svc
from app.services import task_service as svc
from sqlalchemy import select

router = APIRouter(prefix="/tasks", tags=["tasks"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


async def _get_task(session, task_id: PgId, *, lock: bool = False) -> Task:
    """Load a task; lock=True takes a row lock so concurrent mutations serialize."""
    if lock:
        task = await session.scalar(select(Task).where(Task.id == task_id).with_for_update())
    else:
        task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


def _forbid_unless(condition: bool, detail: str) -> None:
    if not condition:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail)


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(data: TaskCreate, user: CurrentUser, session: SessionDep) -> Task:
    return await svc.create_task(session, user, data)


@router.get("", response_model=Page[TaskOut])
async def list_tasks(
    _: CurrentUser,
    session: SessionDep,
    q: str | None = None,
    status: TaskStatus | None = None,
    priority: Priority | None = None,
    assignee_id: PgId | None = None,
    deadline_from: datetime | None = None,
    deadline_to: datetime | None = None,
    sort_by: q_svc.SortBy | None = None,
    order: q_svc.Order | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[TaskOut]:
    deadline_from, deadline_to = ensure_aware(deadline_from), ensure_aware(deadline_to)
    query = q_svc.apply_filters(
        select(Task),
        q=q, status=status, priority=priority, assignee_id=assignee_id,
        deadline_from=deadline_from, deadline_to=deadline_to,
    )
    items, total = await q_svc.paginate(session, q_svc.apply_sort(query, sort_by, order), limit, offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


# Static paths must be registered before "/{task_id}".
@router.get("/overdue", response_model=Page[TaskOut])
async def overdue_tasks(_: CurrentUser, session: SessionDep, limit: Limit = 20, offset: Offset = 0) -> Page[TaskOut]:
    query = q_svc.apply_sort(select(Task).where(q_svc.overdue_condition()), q_svc.SortBy.DEADLINE, q_svc.Order.ASC)
    items, total = await q_svc.paginate(session, query, limit, offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/stats", response_model=TaskStats)
async def stats(_: CurrentUser, session: SessionDep) -> TaskStats:
    return await q_svc.get_stats(session)


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: PgId, _: CurrentUser, session: SessionDep) -> Task:
    return await _get_task(session, task_id)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(task_id: PgId, data: TaskUpdate, user: CurrentUser, session: SessionDep) -> Task:
    task = await _get_task(session, task_id, lock=True)
    _forbid_unless(task.author_id == user.id, "Only the author can edit this task")
    return await svc.update_task(session, task, data)


@router.patch("/{task_id}/status", response_model=TaskOut)
async def change_status(task_id: PgId, data: StatusChange, user: CurrentUser, session: SessionDep) -> Task:
    task = await _get_task(session, task_id, lock=True)
    _forbid_unless(user.id in (task.author_id, task.assignee_id), "Only the author or assignee can change status")
    return await svc.change_status(session, task, data.status)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: PgId, user: CurrentUser, session: SessionDep) -> Response:
    task = await _get_task(session, task_id, lock=True)
    _forbid_unless(task.author_id == user.id, "Only the author can delete this task")
    await svc.delete_task(session, task)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
