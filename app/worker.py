import asyncio
import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import func

from app.config import settings
from app.db import SessionLocal
from app.models import Task, TaskStatus
from app.services.task_service import FINAL_STATUSES

logger = logging.getLogger("app.worker")


async def cancel_overdue(session: AsyncSession) -> int:
    """Cancel every unfinished task whose deadline has passed.

    This is a system action: it deliberately bypasses the user-facing transition map
    (e.g. Review -> Cancelled is not allowed for users but is for the deadline sweep).
    """
    result = await session.execute(
        update(Task)
        .where(Task.deadline < func.now(), Task.status.not_in(FINAL_STATUSES))
        .values(status=TaskStatus.CANCELLED, updated_at=func.now())
    )
    await session.commit()
    return result.rowcount or 0


async def run_forever(factory: async_sessionmaker[AsyncSession] = SessionLocal) -> None:
    while True:
        try:
            async with factory() as session:
                cancelled = await cancel_overdue(session)
            if cancelled:
                logger.info("Auto-cancelled %d overdue task(s)", cancelled)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Overdue sweep failed")
        await asyncio.sleep(settings.worker_interval_seconds)
