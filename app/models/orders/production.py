from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity


class ProductionRecord(Identity, Base):
    __tablename__ = "production_records"
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), index=True)
    department_id: Mapped[UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    production_date: Mapped[date] = mapped_column(Date, index=True)
    planned_quantity: Mapped[int] = mapped_column(Integer)
    actual_quantity: Mapped[int] = mapped_column(Integer)
    defective_quantity: Mapped[int] = mapped_column(Integer)
    reprint_quantity: Mapped[int] = mapped_column(Integer)
    queue_quantity: Mapped[int] = mapped_column(Integer)
    downtime_minutes: Mapped[int] = mapped_column(Integer)
    actual_load_hours: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    lead_time_hours: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    cause: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(
            "planned_quantity>=0 AND actual_quantity>=0 AND defective_quantity>=0 AND defective_quantity<=actual_quantity AND reprint_quantity>=0 AND queue_quantity>=0 AND downtime_minutes>=0 AND actual_load_hours>=0 AND lead_time_hours>=0",
            name="production_values",
        ),
    )


class CapacityPlan(Identity, Base):
    __tablename__ = "capacity_plans"
    plan_date: Mapped[date] = mapped_column(Date, index=True)
    department_id: Mapped[UUID] = mapped_column(ForeignKey("departments.id"))
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"))
    available_hours: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    __table_args__ = (
        UniqueConstraint("plan_date", "department_id", "product_id"),
        CheckConstraint("available_hours>=0", name="capacity_values"),
    )
