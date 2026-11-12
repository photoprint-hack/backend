"""Render entrypoint: serialize migrations, then exec one Uvicorn process."""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings


async def migrate():
    config = get_settings()
    engine = create_async_engine(config.db_url(migrations=True), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT pg_advisory_lock(178901236)"))
            try:
                process = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "alembic", "upgrade", "head"
                )
                if await process.wait() != 0:
                    raise RuntimeError("Database migration failed; refusing to start")
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(178901236)"))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if os.environ.get("MIGRATE_ON_START", "true").lower() == "true":
        asyncio.run(migrate())
    config = get_settings()
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(config.port),
            "--no-access-log",
        ],
    )
