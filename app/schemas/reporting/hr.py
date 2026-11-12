from datetime import date, datetime
from typing import Literal

from app.schemas.analytics.metrics import Context
from app.schemas.common import Schema


class HRSummary(Schema):
    context: Context
    planned_headcount: int | None
    actual_headcount: int | None
    available_headcount: int | None
    required_headcount: int | None
    vacancies_count: int | None
    absences_count: int | None
    staffing_coverage_percent: float | None
    snapshot_dates: list[date]
    notices: list[str]
    updated_at: datetime | None
    status: Literal["ready", "no_data"]
    reason: str | None
