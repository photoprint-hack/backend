from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity, Updated


class Metric(Identity, Updated, Base):
    __tablename__ = "metrics"
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(32))
    formula: Mapped[str] = mapped_column(Text)
    source_description: Mapped[list] = mapped_column(JSONB)
    target_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    direction: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        CheckConstraint(
            "direction IN ('higher_is_better','lower_is_better','range','none')", name="direction"
        ),
    )


class MetricTarget(Identity, Base):
    __tablename__ = "metric_targets"
    metric_id: Mapped[UUID] = mapped_column(ForeignKey("metrics.id"), index=True)
    plan_date: Mapped[date] = mapped_column(Date, index=True)
    department_id: Mapped[UUID] = mapped_column(ForeignKey("departments.id"))
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"))
    target_value: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    __table_args__ = (
        UniqueConstraint("metric_id", "plan_date", "department_id", "product_id"),
        CheckConstraint("target_value>=0", name="target_values"),
    )


class MetricValue(Identity, Base):
    __tablename__ = "metric_values"
    metric_id: Mapped[UUID] = mapped_column(ForeignKey("metrics.id"), index=True)
    department_id: Mapped[UUID | None] = mapped_column(ForeignKey("departments.id"))
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id"))
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date)
    actual_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    target_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    forecast_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    deviation_percent: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    numerator: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    denominator: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    status: Mapped[str] = mapped_column(String(32))
    formula_version: Mapped[str] = mapped_column(String(32), default="1")
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint(
            "metric_id",
            "department_id",
            "product_id",
            "period_start",
            "period_end",
            name="uq_metric_values_context",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "status IN ('normal','warning','critical','no_data') AND period_end>=period_start",
            name="metric_values",
        ),
    )
