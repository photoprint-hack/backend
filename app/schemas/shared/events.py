from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.schemas.common import Schema
from app.schemas.shared.references import UserRef


class AuditOut(Schema):
    id: UUID
    user_id: UUID | None
    actor: UserRef | None
    actor_type: Literal["user", "system"]
    action: str
    object_type: str
    object_id: UUID | None
    object_name: str | None
    old_values: dict[str, Any] | None
    new_values: dict[str, Any] | None
    details: dict[str, Any] | None
    ip_address: str | None
    user_agent: str | None
    status: Literal["success", "failure"]
    error_message: str | None
    request_id: UUID
    created_at: datetime


class ChangeEvent(Schema):
    id: UUID
    object_type: str
    object_id: UUID
    action: str
    changed_by: UserRef | None
    old_values: dict[str, Any]
    new_values: dict[str, Any]
    comment: str | None
    created_at: datetime
