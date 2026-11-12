from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity

FINANCE_TYPES = (
    "revenue",
    "direct_cost",
    "operating_cost",
    "budget_revenue",
    "budget_direct_cost",
    "budget_operating_cost",
    "cash_inflow",
    "cash_outflow",
    "budget_cash_inflow",
    "budget_cash_outflow",
)


class FinanceRecord(Identity, Base):
    __tablename__ = "finance_records"
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    department_id: Mapped[UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id"))
    record_date: Mapped[date] = mapped_column(Date, index=True)
    record_type: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="BYN")
    source_system: Mapped[str] = mapped_column(String(32), default="finance")
    __table_args__ = (
        CheckConstraint("record_type IN " + str(FINANCE_TYPES), name="record_type"),
        CheckConstraint("amount>=0 AND currency='BYN'", name="finance_values"),
    )
