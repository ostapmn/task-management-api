import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TaskStatus(str, enum.Enum):
    BACKLOG = "Backlog"
    IN_PROGRESS = "In Progress"
    REVIEW = "Review"
    DONE = "Done"
    CANCELLED = "Cancelled"


class Priority(str, enum.Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x])


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_assignee_status", "assignee_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(
        _enum(TaskStatus, "task_status"), default=TaskStatus.BACKLOG, server_default=TaskStatus.BACKLOG.value
    )
    priority: Mapped[Priority] = mapped_column(
        _enum(Priority, "task_priority"), default=Priority.MEDIUM, server_default=Priority.MEDIUM.value
    )
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
