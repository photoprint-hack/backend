from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity, Updated


class Customer(Identity, Updated, Base):
    __tablename__ = "customers"
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    customer_type: Mapped[str] = mapped_column(String(8))
    segment: Mapped[str] = mapped_column(String(100))
    acquisition_channel: Mapped[str] = mapped_column(String(100))
    first_order_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("customer_type IN ('b2b','b2c')", name="customer_type"),)


class Product(Identity, Base):
    __tablename__ = "products"
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100))
    standard_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="BYN")
    standard_hours_per_unit: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        CheckConstraint(
            "standard_price >= 0 AND standard_hours_per_unit > 0 AND currency='BYN'", name="product_values"
        ),
    )


class Campaign(Identity, Base):
    __tablename__ = "campaigns"
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(100))
    segment: Mapped[str] = mapped_column(String(100))
    budget: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="BYN")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "budget >= 0 AND currency='BYN' AND (ended_at IS NULL OR ended_at >= started_at)",
            name="campaign_values",
        ),
    )
