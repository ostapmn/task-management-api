from datetime import datetime, timezone
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import Priority, TaskStatus

T = TypeVar("T")

# Postgres INTEGER range; larger ids would otherwise surface as a 500 from the driver.
PgId = Annotated[int, Field(ge=1, le=2_147_483_647)]


def ensure_aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    priority: Priority = Priority.MEDIUM
    assignee_id: PgId | None = None
    deadline: datetime | None = None

    _tz = field_validator("deadline")(ensure_aware)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    priority: Priority | None = None
    assignee_id: PgId | None = None
    deadline: datetime | None = None

    _tz = field_validator("deadline")(ensure_aware)


class StatusChange(BaseModel):
    status: TaskStatus


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    status: TaskStatus
    priority: Priority
    assignee_id: int | None
    author_id: int
    deadline: datetime | None
    created_at: datetime
    updated_at: datetime


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class TaskStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    overdue: int
    active: int
