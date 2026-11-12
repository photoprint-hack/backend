from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.common import Schema


class ImportErrorOut(Schema):
    index: int
    entity_type: str | None
    external_id: str | None
    code: str
    message: str
    fields: dict[str, str]


class ImportRun(Schema):
    run_id: UUID
    source: str
    status: Literal["running", "success", "partial_success", "failed"]
    started_at: datetime
    finished_at: datetime | None
    received: int
    inserted: int
    updated: int
    skipped: int
    failed: int
    errors_total: int
    recalculation_status: str
    recalculation_error: str | None


class ImportResult(ImportRun):
    errors: list[ImportErrorOut]


class SourceStatus(Schema):
    id: UUID
    code: str
    name: str
    source_type: Literal["mock_api"]
    status: Literal["healthy", "warning", "error", "not_loaded"]
    last_sync_at: datetime | None
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    is_stale: bool
    records_count: int
    records_received: int
    records_inserted: int
    records_updated: int
    records_skipped: int
    records_failed: int
    missing_count: int
    duplicate_count: int
    error_count: int
