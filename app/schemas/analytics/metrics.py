from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import Page, Schema
from app.schemas.shared.query import AnalyticsQuery, PaginationQuery
from app.schemas.shared.references import Link


class Context(Schema):
    date_from: date
    date_to: date
    timezone: str = "Europe/Minsk"
    department_id: UUID | None
    product_id: UUID | None
    # Pydantic v2 copies mutable defaults per instance; the literal also keeps
    # the `default: []` shape in the exported OpenAPI schema.
    ignored_filters: list[str] = []  # noqa: RUF012


class Kpi(Schema):
    id: UUID
    code: str
    name: str
    description: str
    category: str
    actual: float | None
    target: float | None
    forecast: float | None
    unit: str
    currency: Literal["BYN"] | None
    achievement_percent: float | None
    deviation_percent: float | None
    status: Literal["normal", "warning", "critical", "no_data"]
    direction: Literal["higher_is_better", "lower_is_better", "range", "none"]
    formula: str
    formula_version: str
    source: list[str]
    updated_at: datetime | None
    source_updated_at: datetime | None
    forecast_method: str | None
    reason_code: str | None
    reason: str | None
    context: Context
    notices: list[str]
    supported_group_by: list[str]


class MetricsQuery(PaginationQuery, AnalyticsQuery):
    category: str | None = None
    status: Literal["normal", "warning", "critical", "no_data"] | None = None
    sort_by: Literal["code", "name"] = "code"
    sort_order: Literal["asc", "desc"] = "asc"


class HistoryQuery(PaginationQuery, AnalyticsQuery):
    interval: Literal["day", "week", "month"] = Field(
        default="day",
        description=(
            "Группировка истории KPI. day: максимум 31 календарный день включительно; "
            "week и month: максимум 366 дней. При превышении диапазона API возвращает 422."
        ),
    )


class BreakdownQuery(PaginationQuery, AnalyticsQuery):
    group_by: Literal["department", "product", "order", "channel", "campaign", "cause"] = "department"


class MetricPoint(Schema):
    period_start: date
    period_end: date
    actual: float | None
    target: float | None
    forecast: float | None
    status: Literal["normal", "warning", "critical", "no_data"]
    updated_at: datetime | None


class BreakdownRow(Schema):
    key: str
    name: str
    actual: float | None
    target: float | None
    deviation_percent: float | None
    source_records_count: int
    cause: str | None
    cause_status: Literal["known", "requires_review"]
    links: list[Link]


class RecalculateResult(Schema):
    calculated_at: datetime
    metric_values_updated: int
    alerts_created: int
    alerts_updated: int


class MetricHistoryPage(Page[MetricPoint]):
    metric_code: str


class BreakdownPage(Page[BreakdownRow]):
    metric_code: str
    group_by: str
    context: Context
