from datetime import date, datetime
from typing import Literal
from uuid import UUID

from app.schemas.analytics.metrics import Context
from app.schemas.common import Schema
from app.schemas.shared.references import Link


class FinancialSource(Schema):
    name: str
    amount: float | None


class Reconciliation(Schema):
    context: Context
    currency: Literal["BYN"]
    period: dict[str, date]
    source_a: FinancialSource
    source_b: FinancialSource
    erp_revenue: float | None
    finance_revenue: float | None
    difference: float | None
    difference_percent: float | None
    status: Literal["normal", "warning", "critical", "no_data"]
    reason: str | None
    checked_at: datetime


class QualityOverview(Schema):
    checked_at: datetime | None
    last_run_id: UUID | None
    sources_total: int
    healthy_sources: int
    stale_sources: int
    open_issues: int
    critical_issues: int
    reconciliation: Reconciliation


class QualityIssue(Schema):
    id: UUID
    created_at: datetime
    source: str
    check_type: str
    severity: Literal["warning", "critical"]
    description: str
    affected_records: int
    status: Literal["open", "resolved"]
    department_id: UUID | None
    checked_at: datetime
    links: list[Link]


class QualityCheckResult(Schema):
    run_id: UUID
    checked_at: datetime
    checks_run: int
    issues_opened: int
    issues_resolved: int
