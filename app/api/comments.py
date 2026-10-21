from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.models import Comment, Task
from app.schemas.comment import CommentCreate, CommentOut
from app.schemas.task import PgId

router = APIRouter(prefix="/tasks/{task_id}/comments", tags=["comments"])


async def _ensure_task(session, task_id: PgId) -> None:
    if await session.get(Task, task_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")


@router.post("", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def add_comment(task_id: PgId, data: CommentCreate, user: CurrentUser, session: SessionDep) -> Comment:
    await _ensure_task(session, task_id)
    comment = Comment(task_id=task_id, author_id=user.id, text=data.text)
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    return comment


@router.get("", response_model=list[CommentOut])
async def list_comments(task_id: PgId, _: CurrentUser, session: SessionDep) -> list[Comment]:
    await _ensure_task(session, task_id)
    result = await session.scalars(select(Comment).where(Comment.task_id == task_id).order_by(Comment.created_at, Comment.id))
    return list(result.all())
