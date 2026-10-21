from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Priority, Task, TaskStatus
from app.schemas.task import TaskStats
from app.services.task_service import ACTIVE_STATUSES, FINAL_STATUSES


class SortBy(str, Enum):
    CREATED_AT = "created_at"
    DEADLINE = "deadline"
    PRIORITY = "priority"


class Order(str, Enum):
    ASC = "asc"
    DESC = "desc"


PRIORITY_RANK = case(
    (Task.priority == Priority.HIGH, 3), (Task.priority == Priority.MEDIUM, 2), else_=1
)


def apply_filters(
    query: Select,
    *,
    q: str | None = None,
    status: TaskStatus | None = None,
    priority: Priority | None = None,
    assignee_id: int | None = None,
    deadline_from: datetime | None = None,
    deadline_to: datetime | None = None,
) -> Select:
    if q:
        pattern = f"%{q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%"
        query = query.where(or_(Task.title.ilike(pattern, escape="\\"), Task.description.ilike(pattern, escape="\\")))
    if status is not None:
        query = query.where(Task.status == status)
    if priority is not None:
        query = query.where(Task.priority == priority)
    if assignee_id is not None:
        query = query.where(Task.assignee_id == assignee_id)
    if deadline_from is not None:
        query = query.where(Task.deadline >= deadline_from)
    if deadline_to is not None:
        query = query.where(Task.deadline <= deadline_to)
    return query


def apply_sort(query: Select, sort_by: SortBy | None, order: Order | None) -> Select:
    """Default: priority High>Medium>Low, then nearest deadline (NULLs last)."""
    if sort_by is None:
        sort_by = SortBy.PRIORITY
        order = Order.DESC
    order = order or Order.ASC
    deadline_asc = Task.deadline.asc().nulls_last()
    if sort_by == SortBy.PRIORITY:
        primary = PRIORITY_RANK.desc() if order == Order.DESC else PRIORITY_RANK.asc()
        return query.order_by(primary, deadline_asc, Task.id)
    if sort_by == SortBy.DEADLINE:
        primary = Task.deadline.desc().nulls_last() if order == Order.DESC else deadline_asc
        return query.order_by(primary, Task.id)
    primary = Task.created_at.desc() if order == Order.DESC else Task.created_at.asc()
    return query.order_by(primary, Task.id)


async def paginate(session: AsyncSession, query: Select, limit: int, offset: int) -> tuple[list[Task], int]:
    total = await session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    items = (await session.scalars(query.limit(limit).offset(offset))).all()
    return list(items), total or 0


def overdue_condition():
    return (Task.deadline < datetime.now(timezone.utc)) & Task.status.not_in(FINAL_STATUSES)


async def get_stats(session: AsyncSession) -> TaskStats:
    by_status = {s.value: 0 for s in TaskStatus}
    for status, count in (await session.execute(select(Task.status, func.count()).group_by(Task.status))).all():
        by_status[status.value] = count
    by_priority = {p.value: 0 for p in Priority}
    for priority, count in (await session.execute(select(Task.priority, func.count()).group_by(Task.priority))).all():
        by_priority[priority.value] = count
    overdue = await session.scalar(select(func.count()).select_from(Task).where(overdue_condition()))
    return TaskStats(
        total=sum(by_status.values()),
        by_status=by_status,
        by_priority=by_priority,
        overdue=overdue or 0,
        active=sum(by_status[s.value] for s in ACTIVE_STATUSES),
    )
