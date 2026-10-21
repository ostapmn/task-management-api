import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import auth, comments, tasks
from app.config import settings
from app.services.task_service import DomainError
from app.worker import run_forever

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = asyncio.create_task(run_forever()) if settings.worker_enabled else None
    try:
        yield
    finally:
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


app = FastAPI(title="Task Management API", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(comments.router)


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
