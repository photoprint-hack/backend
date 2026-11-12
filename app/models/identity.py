from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity, Updated

ROLES = ("admin", "director", "manager", "analyst", "employee")


class Department(Identity, Updated, Base):
    __tablename__ = "departments"
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class User(Identity, Updated, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin','director','manager','analyst','employee')", name="role"),
        CheckConstraint(
            "role NOT IN ('manager','employee') OR department_id IS NOT NULL", name="department_required"
        ),
        CheckConstraint("email = lower(email)", name="email_normalized"),
    )
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))
    department_id: Mapped[UUID | None] = mapped_column(ForeignKey("departments.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class RefreshToken(Identity, Base):
    __tablename__ = "refresh_tokens"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[UUID] = mapped_column(index=True)
    jti: Mapped[UUID] = mapped_column(unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("refresh_tokens.id"))
    __table_args__ = (
        Index("ix_refresh_tokens_active_user", "user_id", postgresql_where=text("revoked_at IS NULL")),
    )
