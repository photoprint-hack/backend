from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity, Updated


class Order(Identity, Updated, Base):
    __tablename__ = "orders"
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    order_number: Mapped[str] = mapped_column(String(100), unique=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), index=True)
    department_id: Mapped[UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    campaign_id: Mapped[UUID | None] = mapped_column(ForeignKey("campaigns.id"))
    crm_deal_id: Mapped[UUID | None] = mapped_column(ForeignKey("crm_deals.id"), unique=True)
    channel: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer)
    standard_hours_per_unit: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="BYN")
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    moderation_status: Mapped[str] = mapped_column(String(32), default="pending")
    production_status: Mapped[str] = mapped_column(String(32), default="queued")
    delivery_status: Mapped[str] = mapped_column(String(32), default="not_started")
    has_defect: Mapped[bool] = mapped_column(Boolean, default=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    source_system: Mapped[str] = mapped_column(String(32), default="erp")
    __table_args__ = (
        CheckConstraint("status IN ('new','in_progress','completed','cancelled')", name="status"),
        CheckConstraint(
            "moderation_status IN ('pending','approved','rejected','revision_required')",
            name="moderation_status",
        ),
        CheckConstraint(
            "production_status IN ('queued','in_progress','completed','blocked')", name="production_status"
        ),
        CheckConstraint(
            "delivery_status IN ('not_started','in_transit','delivered','delayed','returned')",
            name="delivery_status",
        ),
        CheckConstraint(
            "quantity>0 AND standard_hours_per_unit>0 AND amount>=0 AND currency='BYN' AND version>0",
            name="order_values",
        ),
        CheckConstraint("status != 'completed' OR completed_at IS NOT NULL", name="completion_required"),
        CheckConstraint("completed_at IS NULL OR completed_at >= created_at", name="completion_time"),
        Index("ix_orders_department_created", "department_id", "created_at"),
    )


class OrderEvent(Identity, Base):
    __tablename__ = "order_events"
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    old_status: Mapped[str | None] = mapped_column(String(32))
    new_status: Mapped[str | None] = mapped_column(String(32))
    department_id: Mapped[UUID | None] = mapped_column(ForeignKey("departments.id"))
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    source_system: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)
    cause: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
