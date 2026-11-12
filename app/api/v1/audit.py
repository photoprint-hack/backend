from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import AwareDatetime
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.exceptions import ApiError
from app.core.permissions import require_role
from app.models import AuditLog, User
from app.schemas.common import Data, Page, Schema, page
from app.schemas.shared.events import AuditOut
from app.services.scoping import like_pattern
from app.services.serialization import columns

router = APIRouter(tags=["audit"])


class AuditQuery(Schema):
    page: int = Query(1, ge=1)
    page_size: int = Query(20, ge=1, le=100)
    user_id: UUID | None = None
    action: str | None = None
    object_type: str | None = None
    object_id: UUID | None = None
    status: Literal["success", "failure"] | None = None
    date_from: date | AwareDatetime | None = None
    date_to: date | AwareDatetime | None = None
    search: str | None = Query(None, min_length=1, max_length=200)
    sort_by: Literal["created_at"] = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"


async def serialize_logs(db, rows):
    actors = {
        x.id: x.full_name
        for x in (
            await db.scalars(select(User).where(User.id.in_({r.user_id for r in rows if r.user_id})))
        ).all()
    }
    return [
        {
            **columns(row),
            "actor": {"id": row.user_id, "full_name": actors[row.user_id]} if row.user_id in actors else None,
        }
        for row in rows
    ]


@router.get("/audit-logs", response_model=Page[AuditOut])
async def logs(db: DB, user: CurrentUser, query: Annotated[AuditQuery, Query()]):
    require_role(user, {"admin", "director"})
    stmt = select(AuditLog)
    for field in ["user_id", "action", "object_type", "object_id", "status"]:
        value = getattr(query, field)
        if value is not None:
            stmt = stmt.where(getattr(AuditLog, field) == value)
    from app.core.config import get_settings

    zone = ZoneInfo(get_settings().report_timezone)
    if query.date_from:
        lower = (
            query.date_from
            if isinstance(query.date_from, datetime)
            else datetime.combine(query.date_from, time.min, zone)
        )
        stmt = stmt.where(AuditLog.created_at >= lower)
    if query.date_to:
        if isinstance(query.date_to, datetime):
            stmt = stmt.where(AuditLog.created_at <= query.date_to)
        else:
            stmt = stmt.where(
                AuditLog.created_at < datetime.combine(query.date_to + timedelta(days=1), time.min, zone)
            )
    if query.search:
        from sqlalchemy import String, cast, or_

        pattern = like_pattern(query.search)
        stmt = stmt.where(
            or_(
                AuditLog.object_name.ilike(pattern, escape="\\"),
                cast(AuditLog.object_id, String).ilike(pattern, escape="\\"),
            )
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.scalars(
            stmt.order_by(
                AuditLog.created_at.asc() if query.sort_order == "asc" else AuditLog.created_at.desc(),
                AuditLog.id,
            )
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    return page(await serialize_logs(db, rows), total, query.page, query.page_size)


@router.get("/audit-logs/{identifier}", response_model=Data[AuditOut])
async def log(identifier: UUID, db: DB, user: CurrentUser):
    require_role(user, {"admin", "director"})
    row = await db.get(AuditLog, identifier)
    if not row:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Запись аудита не найдена")
    return {"data": (await serialize_logs(db, [row]))[0]}
