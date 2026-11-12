from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity, Updated


class Deal(Identity, Updated, Base):
    __tablename__ = "crm_deals"
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id"), index=True)
    department_id: Mapped[UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    campaign_id: Mapped[UUID | None] = mapped_column(ForeignKey("campaigns.id"))
    channel: Mapped[str] = mapped_column(String(100))
    segment: Mapped[str] = mapped_column(String(100))
    stage: Mapped[str] = mapped_column(String(32))
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="BYN")
    order_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("orders.id", use_alter=True, name="fk_crm_deals_order_id_orders"), unique=True
    )
    __table_args__ = (
        CheckConstraint(
            "stage IN ('new','qualified','proposal','won','lost') AND expected_amount>=0 AND currency='BYN'",
            name="deal_values",
        ),
    )


class DealEvent(Identity, Base):
    __tablename__ = "crm_deal_events"
    deal_id: Mapped[UUID] = mapped_column(ForeignKey("crm_deals.id"), index=True)
    old_stage: Mapped[str | None] = mapped_column(String(32))
    new_stage: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
