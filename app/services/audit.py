from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User

SECRET_KEYS = ("password", "token", "secret", "authorization", "cookie", "database_url")


def safe_values(value):
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if any(s in str(k).lower() for s in SECRET_KEYS) else safe_values(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [safe_values(v) for v in value]
    if isinstance(value, (UUID, datetime, Decimal)):
        return str(value)
    return value


def record(
    db: AsyncSession,
    action: str,
    object_type: str,
    *,
    actor: User | None = None,
    object_id: UUID | None = None,
    object_name: str | None = None,
    old: dict | None = None,
    new: dict | None = None,
    details: dict | None = None,
    status: str = "success",
    request: Request | None = None,
):
    db.add(
        AuditLog(
            user_id=actor.id if actor else None,
            actor_type="user" if actor else "system",
            action=action,
            object_type=object_type,
            object_id=object_id,
            object_name=object_name,
            old_values=safe_values(old),
            new_values=safe_values(new),
            details=safe_values(details),
            status=status,
            request_id=getattr(request.state, "request_id", uuid4()) if request else uuid4(),
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent", "")[:500] if request else None,
        )
    )
