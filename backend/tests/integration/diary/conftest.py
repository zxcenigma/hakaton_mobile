"""PostgreSQL tests use disposable databases, never the application tables."""
import asyncio
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url

from monoapi.apps.fastapi import api
from monoapi.core import settings
from monoapi.db._session import AsyncSessionManager
from monoapi.db.models import UserModel
from monoapi.routers.services import _base

BACKEND = Path(__file__).resolve().parents[3]


def migrate(db_name, *args, check=True):
    env = {**os.environ, "PG_DB": db_name, "ECHO": "false"}
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND,
                            env=env, capture_output=True, text=True)
    if check and result.returncode:
        pytest.fail(result.stdout + result.stderr)
    return result


async def admin_execute(query):
    url = make_url(settings.db.db_async_url)
    conn = await asyncpg.connect(host=url.host, port=url.port, user=url.username,
                                 password=url.password, database=url.database)
    try:
        await conn.execute(query)
    finally:
        await conn.close()


@contextmanager
def disposable_database():
    name = "diary_test_" + uuid4().hex
    try:
        asyncio.run(admin_execute(f'CREATE DATABASE "{name}"'))
    except (OSError, asyncpg.PostgresError) as exc:
        if os.getenv("DIARY_REQUIRE_POSTGRES") == "1":
            pytest.fail(f"Test PostgreSQL unavailable: {type(exc).__name__}")
        pytest.skip(f"Test PostgreSQL unavailable: {type(exc).__name__}")
    try:
        yield name
    finally:
        asyncio.run(admin_execute(f'DROP DATABASE "{name}" WITH (FORCE)'))


@pytest.fixture(scope="session")
def postgres_database():
    with disposable_database() as name:
        migrate(name, "upgrade", "head")
        yield name


@pytest_asyncio.fixture
async def db(postgres_database, monkeypatch):
    url = make_url(settings.db.db_async_url).set(database=postgres_database)
    manager = AsyncSessionManager(host=url.render_as_string(hide_password=False), echo=False,
                                  pool_max_overflow=20, pool_size=5, pool_timeout=10, pool_recycle=300)
    monkeypatch.setattr(_base, "async_session_manager", manager)
    async with manager.session() as session:
        users = [UserModel(email=f"{uuid4().hex}@example.com", username="diary", password="test") for _ in range(2)]
        session.add_all(users)
        await session.commit()
        user_ids = [str(user.uuid) for user in users]
    yield manager, user_ids
    await manager.close()


@pytest_asyncio.fixture
async def client(db):
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as http:
        yield http
