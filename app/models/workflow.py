from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity, Updated


class Decision(Identity, Updated, Base):
    __tablename__ = "decisions"
    alert_id: Mapped[UUID | None] = mapped_column(ForeignKey("alerts.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    problem: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(Text)
    cause: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    department_id: Mapped[UUID | None] = mapped_column(ForeignKey("departments.id"), index=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    priority: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    expected_result: Mapped[str] = mapped_column(Text)
    actual_result: Mapped[str | None] = mapped_column(Text)
    verification_note: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        CheckConstraint(
            "status IN ('new','in_progress','needs_review','completed','cancelled')", name="status"
        ),
        CheckConstraint(
            "priority IN ('low','medium','high','critical') AND version>0", name="decision_values"
        ),
        CheckConstraint(
            "status NOT IN ('needs_review','completed') OR length(trim(actual_result))>0 AND actual_result IS NOT NULL",
            name="actual_result_required",
        ),
        CheckConstraint(
            "status!='completed' OR verification_note IS NOT NULL AND completed_at IS NOT NULL",
            name="verification_required",
        ),
    )


class DecisionHistory(Identity, Base):
    __tablename__ = "decision_history"
    decision_id: Mapped[UUID] = mapped_column(ForeignKey("decisions.id"), index=True)
    changed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    old_values: Mapped[dict] = mapped_column(JSONB, default=dict)
    new_values: Mapped[dict] = mapped_column(JSONB, default=dict)
    comment: Mapped[str | None] = mapped_column(Text)


class Task(Identity, Updated, Base):
    __tablename__ = "tasks"
    decision_id: Mapped[UUID | None] = mapped_column(ForeignKey("decisions.id"), index=True)
    alert_id: Mapped[UUID | None] = mapped_column(ForeignKey("alerts.id"))
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id"), index=True)
    department_id: Mapped[UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    assignee_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    priority: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        CheckConstraint(
            "status IN ('new','in_progress','completed','cancelled') AND priority IN ('low','medium','high','critical') AND version>0",
            name="task_values",
        ),
        CheckConstraint("status!='completed' OR completed_at IS NOT NULL", name="completion_required"),
    )
