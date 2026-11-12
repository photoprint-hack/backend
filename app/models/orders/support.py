from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity


class SupportInteraction(Identity, Base):
    __tablename__ = "support_interactions"
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"))
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id"), index=True)
    department_id: Mapped[UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    channel: Mapped[str] = mapped_column(String(100))
    topic: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32))
    priority: Mapped[str] = mapped_column(String(32))
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(Text)
    cause: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("status IN ('open','in_progress','closed')", name="status"),
        CheckConstraint("status!='closed' OR closed_at IS NOT NULL", name="closed_time"),
    )
