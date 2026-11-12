from datetime import date, datetime
from typing import Literal
from uuid import UUID

from app.schemas.analytics.metrics import Context
from app.schemas.common import Schema
from app.schemas.shared.query import AnalyticsQuery, PaginationQuery, SearchQuery


class ProductionQuery(SearchQuery, AnalyticsQuery):
    order_id: UUID | None = None
    sort_by: str = "production_date"


class QueueQuery(PaginationQuery):
    department_id: UUID | None = None
    product_id: UUID | None = None


class ProductionOut(Schema):
    id: UUID
    external_id: str | None
    order_id: UUID | None
    product_id: UUID
    department_id: UUID
    production_date: date
    planned_quantity: int
    actual_quantity: int
    defective_quantity: int
    reprint_quantity: int
    queue_quantity: int
    downtime_minutes: int
    actual_load_hours: float
    lead_time_hours: float
    cause: str | None
    source_system: Literal["erp"]
    created_at: datetime


class ProductionSummary(Schema):
    context: Context
    planned_quantity: int | None
    actual_quantity: int | None
    plan_achievement_percent: float | None
    queue_quantity: int | None
    average_lead_time_hours: float | None
    actual_load_hours: float | None
    available_capacity_hours: float | None
    capacity_utilization_percent: float | None
    downtime_minutes: int | None
    defective_quantity: int | None
    reprint_quantity: int | None
    defect_rate_percent: float | None
    updated_at: datetime | None
    status: Literal["ready", "no_data"]
    reason: str | None
