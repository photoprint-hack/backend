from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity


class ForecastRecord(Identity, Base):
    __tablename__ = "forecast_records"
    department_id: Mapped[UUID | None] = mapped_column(ForeignKey("departments.id"))
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id"))
    as_of: Mapped[date] = mapped_column(Date)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    demand: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    available_capacity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    deficit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    reserve: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    method: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index(
            "uq_forecast_context",
            "as_of",
            "period_start",
            "department_id",
            "product_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )
