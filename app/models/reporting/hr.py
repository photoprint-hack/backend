from datetime import date
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity


class HRSnapshot(Identity, Base):
    __tablename__ = "hr_snapshots"
    department_id: Mapped[UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    planned_headcount: Mapped[int] = mapped_column(Integer)
    actual_headcount: Mapped[int] = mapped_column(Integer)
    available_headcount: Mapped[int] = mapped_column(Integer)
    required_headcount: Mapped[int] = mapped_column(Integer)
    vacancies_count: Mapped[int] = mapped_column(Integer)
    absences_count: Mapped[int] = mapped_column(Integer)
    source_system: Mapped[str] = mapped_column(String(32), default="hr")
    __table_args__ = (
        UniqueConstraint("department_id", "snapshot_date"),
        CheckConstraint(
            "planned_headcount>=0 AND actual_headcount>=0 AND available_headcount>=0 AND required_headcount>=0 AND vacancies_count>=0 AND absences_count>=0 AND available_headcount<=actual_headcount",
            name="hr_values",
        ),
    )
