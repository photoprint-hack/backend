from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity


class AuditLog(Identity, Base):
    __tablename__ = "audit_logs"
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    actor_type: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(64), index=True)
    object_type: Mapped[str] = mapped_column(String(64), index=True)
    object_id: Mapped[UUID | None]
    object_name: Mapped[str | None] = mapped_column(String(200))
    old_values: Mapped[dict | None] = mapped_column(JSONB)
    new_values: Mapped[dict | None] = mapped_column(JSONB)
    details: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16))
    error_message: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[UUID] = mapped_column(index=True)
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user','system') AND status IN ('success','failure')", name="audit_values"
        ),
        Index("ix_audit_logs_created_at", "created_at"),
    )
