from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Task, TaskStatus, User
from app.schemas.task import TaskCreate, TaskUpdate

ACTIVE_STATUSES = (TaskStatus.BACKLOG, TaskStatus.IN_PROGRESS, TaskStatus.REVIEW)
FINAL_STATUSES = (TaskStatus.DONE, TaskStatus.CANCELLED)
ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.BACKLOG: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
    TaskStatus.IN_PROGRESS: {TaskStatus.REVIEW, TaskStatus.CANCELLED},
    TaskStatus.REVIEW: {TaskStatus.DONE},
    TaskStatus.DONE: set(),
    TaskStatus.CANCELLED: set(),
}
DELETABLE_STATUSES = (TaskStatus.BACKLOG, TaskStatus.DONE, TaskStatus.CANCELLED)


class DomainError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _check_deadline_not_past(deadline: datetime | None) -> None:
    if deadline is not None and deadline < _now():
        raise DomainError(422, "Deadline cannot be in the past")


async def _check_assignee_capacity(session: AsyncSession, assignee_id: int, exclude_task_id: int | None) -> None:
    """Lock the assignee row so concurrent assignments serialize, then enforce the active-task cap."""
    user = await session.scalar(select(User).where(User.id == assignee_id).with_for_update())
    if user is None:
        raise DomainError(422, f"Assignee {assignee_id} does not exist")
    query = select(func.count()).select_from(Task).where(
        Task.assignee_id == assignee_id, Task.status.in_(ACTIVE_STATUSES)
    )
    if exclude_task_id is not None:
        query = query.where(Task.id != exclude_task_id)
    if (await session.scalar(query)) >= settings.max_active_tasks:
        raise DomainError(409, f"Assignee already has {settings.max_active_tasks} active tasks")


async def create_task(session: AsyncSession, author: User, data: TaskCreate) -> Task:
    _check_deadline_not_past(data.deadline)
    if data.assignee_id is not None:
        await _check_assignee_capacity(session, data.assignee_id, None)
    task = Task(**data.model_dump(), author_id=author.id)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def update_task(session: AsyncSession, task: Task, data: TaskUpdate) -> Task:
    if task.status in FINAL_STATUSES:
        raise DomainError(409, f"Task in status '{task.status.value}' cannot be edited")
    changes = data.model_dump(exclude_unset=True)
    if "title" in changes and changes["title"] is None:
        raise DomainError(422, "title cannot be null")
    if "priority" in changes and changes["priority"] is None:
        raise DomainError(422, "priority cannot be null")
    if "deadline" in changes:
        _check_deadline_not_past(changes["deadline"])
    if "assignee_id" in changes and changes["assignee_id"] != task.assignee_id:
        if task.status == TaskStatus.REVIEW:
            raise DomainError(409, "Assignee cannot be changed once the task is in Review")
        if changes["assignee_id"] is not None:
            await _check_assignee_capacity(session, changes["assignee_id"], task.id)
    for field, value in changes.items():
        setattr(task, field, value)
    await session.commit()
    await session.refresh(task)
    return task


async def change_status(session: AsyncSession, task: Task, new_status: TaskStatus) -> Task:
    if new_status not in ALLOWED_TRANSITIONS[task.status]:
        raise DomainError(409, f"Transition '{task.status.value}' -> '{new_status.value}' is not allowed")
    if new_status == TaskStatus.DONE:
        if task.assignee_id is None:
            raise DomainError(409, "Task cannot be Done without an assignee")
        if task.deadline is not None and task.deadline < _now():
            raise DomainError(409, "Task cannot be Done after its deadline has passed")
    task.status = new_status
    await session.commit()
    await session.refresh(task)
    return task


async def delete_task(session: AsyncSession, task: Task) -> None:
    if task.status not in DELETABLE_STATUSES:
        raise DomainError(
            409, f"Task in status '{task.status.value}' cannot be deleted; cancel or finish it first"
        )
    await session.delete(task)
    await session.commit()
