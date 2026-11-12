from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Identity


class SourceRecord(Identity, Base):
    __tablename__ = "source_records"
    source_name: Mapped[str] = mapped_column(String(32))
    entity_type: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(200))
    platform_id: Mapped[UUID | None]
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processing_status: Mapped[str] = mapped_column(String(32))
    content_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("source_name", "entity_type", "external_id"),)


class SourceSyncRun(Identity, Base):
    __tablename__ = "source_sync_runs"
    source_name: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_received: Mapped[int] = mapped_column(Integer, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)
    records_failed: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSONB, default=list)
    error_message: Mapped[str | None] = mapped_column(Text)
    recalculation_status: Mapped[str] = mapped_column(String(32), default="not_required")
    recalculation_error: Mapped[str | None] = mapped_column(Text)


class DataQualityRun(Identity, Base):
    __tablename__ = "data_quality_runs"
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_name: Mapped[str | None] = mapped_column(String(32))
    checks_run: Mapped[int] = mapped_column(Integer)
    issues_opened: Mapped[int] = mapped_column(Integer)
    issues_resolved: Mapped[int] = mapped_column(Integer)


class DataQualityIssue(Identity, Base):
    __tablename__ = "data_quality_issues"
    source_name: Mapped[str] = mapped_column(String(32), index=True)
    check_type: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    affected_records: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="open")
    department_id: Mapped[UUID | None] = mapped_column(ForeignKey("departments.id"))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(200), unique=True)
