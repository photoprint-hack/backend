import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.schemas.common import Data, Schema

router = APIRouter(tags=["health"])


class Health(Schema):
    status: str
    database: str
    version: str


@router.get("", response_model=Data[Health], responses={503: {"model": Data[Health]}})
async def health():
    try:
        async with asyncio.timeout(3):
            async with get_session_factory()() as db:
                await db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "data": {
                    "status": "degraded",
                    "database": "unavailable",
                    "version": get_settings().app_version,
                }
            },
        )
    return {"data": {"status": "ok", "database": "connected", "version": get_settings().app_version}}
