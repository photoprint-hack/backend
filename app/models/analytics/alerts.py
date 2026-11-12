from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity, Updated


class Alert(Identity, Updated, Base):
    __tablename__ = "alerts"
    metric_value_id: Mapped[UUID | None] = mapped_column(ForeignKey("metric_values.id"))
    metric_code: Mapped[str] = mapped_column(ForeignKey("metrics.code"))
    department_id: Mapped[UUID | None] = mapped_column(ForeignKey("departments.id"), index=True)
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    deviation_percent: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    actual: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    target: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    opening_actual: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    opening_target: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    severity: Mapped[str] = mapped_column(String(32), default="critical")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    __table_args__ = (
        UniqueConstraint(
            "metric_code",
            "period_start",
            "department_id",
            "product_id",
            name="uq_alerts_monthly_context",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "status IN ('active','acknowledged','resolved') AND severity='critical' AND period_end>=period_start",
            name="alert_values",
        ),
    )
