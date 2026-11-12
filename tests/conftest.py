import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ["APP_ENV"] = "testing"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused"
os.environ["JWT_SECRET_KEY"] = "test-only-signing-key-which-is-at-least-32-bytes"
os.environ["COOKIE_SECURE"] = "false"
os.environ["COOKIE_SAMESITE"] = "lax"
os.environ["FRONTEND_URL"] = "http://localhost:5173"
os.environ["BACKEND_URL"] = "http://localhost:8000"
os.environ["REPORT_TIMEZONE"] = "Europe/Minsk"
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["METABASE_URL"] = ""
os.environ["METABASE_DASHBOARD_IDS"] = "{}"
os.environ["METABASE_VERIFIED_DASHBOARDS"] = "[]"
for role in ["ADMIN", "DIRECTOR", "MANAGER", "ANALYST", "EMPLOYEE"]:
    os.environ["DEMO_" + role + "_PASSWORD"] = "SeedPassword123!"

from app.db.session import get_db  # noqa: E402 -- Override local settings before app import.
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def project_root():
    return Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def database(project_root):
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL is not configured; PostgreSQL integration not run")
    schema = "test_photoprint_" + uuid4().hex
    # model_copy does not coerce SecretStr; validate a clean Settings instance instead.
    from app.core.config import Settings

    config = Settings(_env_file=None, database_url=raw, jwt_secret_key=os.environ["JWT_SECRET_KEY"])
    bootstrap = create_async_engine(config.db_url())
    async with bootstrap.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(config.db_url(), connect_args={"server_settings": {"search_path": schema}})
    migration_path = project_root / "alembic/versions/20261112_01_domain.py"
    spec = importlib.util.spec_from_file_location("domain_revision", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        async with engine.begin() as conn:

            def migrate(sync_connection):
                with Operations.context(MigrationContext.configure(sync_connection)):
                    module.upgrade()
                    views_spec = importlib.util.spec_from_file_location(
                        "bi_views_revision",
                        project_root / "alembic/versions/20261112_02_bi_views.py",
                    )
                    views = importlib.util.module_from_spec(views_spec)
                    views_spec.loader.exec_module(views)
                    views.upgrade()
                    for number in ("03", "04", "05"):
                        extra_spec = importlib.util.spec_from_file_location(
                            "impact_revision_" + number,
                            project_root / f"alembic/versions/20261112_{number}_impact.py",
                        )
                        extra = importlib.util.module_from_spec(extra_spec)
                        extra_spec.loader.exec_module(extra)
                        extra.upgrade()

            await conn.run_sync(migrate)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        yield factory
    finally:
        await engine.dispose()
        async with bootstrap.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await bootstrap.dispose()


@pytest_asyncio.fixture
async def client(database):
    async def override(request: Request):
        request.state.session_factory = database
        async with database() as db:
            yield db
            await db.rollback()

    app.dependency_overrides[get_db] = override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seeded_database(database):
    from app.seed.service import seed

    passwords = {role: "SeedPassword123!" for role in ["admin", "director", "manager", "analyst", "employee"]}
    async with database() as db:
        await seed(db, passwords=passwords)
        await db.commit()


@pytest_asyncio.fixture
async def seeded(seeded_database, client):
    response = await client.post(
        "/api/v1/auth/login", json={"email": "director@fotoprint.demo", "password": "SeedPassword123!"}
    )
    assert response.status_code == 200, response.text
    return AuthHeaders({"Authorization": "Bearer " + response.json()["data"]["access_token"]})


@pytest_asyncio.fixture
async def minimal_admin(database, client):
    from app.core.security import hash_password
    from app.models import User

    async with database() as db:
        user = User(
            email="import-admin@example.com",
            full_name="Import administrator",
            role="admin",
            is_active=True,
            password_hash=hash_password("ImportPassword123!"),
        )
        db.add(user)
        await db.commit()
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "ImportPassword123!"}
    )
    assert response.status_code == 200, response.text
    return AuthHeaders({"Authorization": "Bearer " + response.json()["data"]["access_token"]})


class AuthHeaders(dict):
    def __repr__(self):
        return "<test authorization headers>"
