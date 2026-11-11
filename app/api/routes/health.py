from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("")
async def liveness() -> dict[str, str]:
    """Always-on liveness probe; does not touch the database."""
    return {"status": "ok"}


@router.get("/db")
async def database_readiness(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Readiness probe that verifies the database connection."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ok", "database": "up"}
