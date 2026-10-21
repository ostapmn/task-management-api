"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-21
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STATUSES = ("Backlog", "In Progress", "Review", "Done", "Cancelled")
PRIORITIES = ("Low", "Medium", "High")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255)),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    status = postgresql.ENUM(*STATUSES, name="task_status", create_type=False)
    priority = postgresql.ENUM(*PRIORITIES, name="task_priority", create_type=False)
    status.create(op.get_bind(), checkfirst=True)
    priority.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("status", status, nullable=False, server_default="Backlog"),
        sa.Column("priority", priority, nullable=False, server_default="Medium"),
        sa.Column("assignee_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("author_id", sa.Integer, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tasks_deadline", "tasks", ["deadline"])
    op.create_index("ix_tasks_assignee_status", "tasks", ["assignee_id", "status"])

    op.create_table(
        "comments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("task_id", sa.Integer, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Integer, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_comments_task_id", "comments", ["task_id"])


def downgrade() -> None:
    op.drop_table("comments")
    op.drop_table("tasks")
    op.execute("DROP TYPE IF EXISTS task_status")
    op.execute("DROP TYPE IF EXISTS task_priority")
    op.drop_table("users")
