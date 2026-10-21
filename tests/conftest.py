import os
from datetime import datetime, timedelta, timezone

os.environ["WORKER_ENABLED"] = "false"
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-0123456789abcdef0123456789")

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db import Base, get_session
from app.main import app
from app.models import Task

TEST_DB = "app_test"
PASSWORD = "password123"


def _test_url() -> str:
    return make_url(settings.database_url).set(database=TEST_DB).render_as_string(hide_password=False)


@pytest_asyncio.fixture(scope="session")
async def engine():
    base = make_url(settings.database_url)
    admin = await asyncpg.connect(
        user=base.username, password=base.password, host=base.host, port=base.port, database=base.database
    )
    try:
        if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", TEST_DB):
            await admin.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await admin.close()
    engine = create_async_engine(_test_url(), poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE comments, tasks, users RESTART IDENTITY CASCADE"))
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(session_factory):
    async def override():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def make_user(client):
    """Register + log in a user; returns (user_id, auth_headers)."""

    async def _make(email: str):
        r = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
        assert r.status_code == 201, r.text
        r2 = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
        assert r2.status_code == 200, r2.text
        return r.json()["id"], {"Authorization": f"Bearer {r2.json()['access_token']}"}

    return _make


@pytest_asyncio.fixture
async def alice(make_user):
    return await make_user("alice@example.com")


@pytest_asyncio.fixture
async def bob(make_user):
    return await make_user("bob@example.com")


@pytest_asyncio.fixture
async def insert_task(session_factory):
    """Insert a task straight into the DB (bypasses API validation, e.g. for past deadlines)."""

    async def _insert(author_id: int, **fields) -> int:
        fields.setdefault("title", "direct")
        async with session_factory() as s:
            task = Task(author_id=author_id, **fields)
            s.add(task)
            await s.commit()
            return task.id

    return _insert


def future_dt(days: float = 1) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def future(days: float = 1) -> str:
    return future_dt(days).isoformat()


def past(days: float = 1) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)
