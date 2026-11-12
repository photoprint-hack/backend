"""Additive impact-map and communication persistence; business execution remains Task."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity, Updated


class DepartmentResponsibility(Identity, Updated, Base):
    __tablename__ = "department_responsibilities"
    department_id: Mapped[UUID] = mapped_column(ForeignKey("departments.id"), unique=True)
    head_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    director_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)


class MetricResponsibility(Identity, Updated, Base):
    __tablename__ = "metric_responsibilities"
    metric_code: Mapped[str] = mapped_column(ForeignKey("metrics.code"))
    department_id: Mapped[UUID | None] = mapped_column(ForeignKey("departments.id"))
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        Index(
            "uq_metric_responsibility_scope",
            "metric_code",
            "department_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )


class ManagementAction(Identity, Updated, Base):
    __tablename__ = "management_actions"
    type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    author_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    assignee_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    department_id: Mapped[UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(32))
    metric_code: Mapped[str | None] = mapped_column(ForeignKey("metrics.code"))
    source_ref: Mapped[dict | None] = mapped_column(JSONB)
    context: Mapped[dict] = mapped_column(JSONB)
    scoped_context: Mapped[dict] = mapped_column(JSONB)
    decision_id: Mapped[UUID | None] = mapped_column(ForeignKey("decisions.id"))
    alert_id: Mapped[UUID | None] = mapped_column(ForeignKey("alerts.id"))
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id"))
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    planned_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    calendar_version: Mapped[str | None] = mapped_column(String(64))
    assignment_cycle: Mapped[int] = mapped_column(Integer, default=0)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    result: Mapped[str | None] = mapped_column(Text)
    result_refs: Mapped[list] = mapped_column(JSONB, default=list)
    verification_note: Mapped[str | None] = mapped_column(Text)
    routing_issue: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        CheckConstraint("type IN ('reminder','explanation_request','task')", name="type"),
        CheckConstraint(
            "status IN ('draft','sent','acknowledged','in_progress','resolved','verified','rejected','cancelled')",
            name="status",
        ),
        CheckConstraint(
            "priority IN ('low','medium','high','critical') AND version>0 AND assignment_cycle>=0",
            name="values",
        ),
        CheckConstraint("status='draft' OR assignee_id IS NOT NULL OR status='cancelled'", name="recipient"),
        Index(
            "uq_action_active_task",
            "task_id",
            unique=True,
            postgresql_where=sql_text(
                "task_id IS NOT NULL AND status NOT IN ('draft','verified','rejected','cancelled')"
            ),
        ),
    )


class NotificationOutbox(Identity, Base):
    __tablename__ = "notification_outbox"
    action_id: Mapped[UUID] = mapped_column(ForeignKey("management_actions.id"), index=True)
    recipient_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    deduplication_key: Mapped[str] = mapped_column(String(250), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        CheckConstraint("status IN ('pending','processing','sent','failed') AND attempts>=0", name="values"),
    )


class Notification(Identity, Base):
    __tablename__ = "notifications"
    outbox_id: Mapped[UUID] = mapped_column(ForeignKey("notification_outbox.id"), unique=True)
    action_id: Mapped[UUID] = mapped_column(ForeignKey("management_actions.id"), index=True)
    recipient_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIAnalysis(Identity, Base):
    __tablename__ = "ai_analyses"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True)
    request_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    model: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("user_id", "request_key"),)


class MaryEvent(Identity, Base):
    __tablename__ = "mary_events"
    external_id: Mapped[str] = mapped_column(String(200), unique=True)
    event_type: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    department_id: Mapped[UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id"))
    metadata_safe: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('conversation_started','conversation_resolved','conversation_handoff','lead_qualified','order_intent_detected')",
            name="type",
        ),
    )
