from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.analytics.metrics import Context
from app.schemas.common import Schema
from app.schemas.shared.query import AnalyticsQuery, SearchQuery


class DealsQuery(SearchQuery, AnalyticsQuery):
    stage: Literal["new", "qualified", "proposal", "won", "lost"] | None = None
    channel: str | None = None
    campaign_id: UUID | None = None


class SalesSlice(Schema):
    code: str
    name: str
    orders_count: int
    revenue: float
    active_customers: int


class SalesSummary(Schema):
    context: Context
    revenue: float | None
    orders_count: int | None
    average_check: float | None
    new_customers: int | None
    active_customers: int | None
    repeat_purchase_rate: float | None
    sales_plan_achievement: float | None
    conversion_percent: float | None
    currency: Literal["BYN"]
    channels: list[SalesSlice]
    segments: list[SalesSlice]
    updated_at: datetime


class FunnelStage(Schema):
    code: Literal["new", "qualified", "proposal", "won", "lost"]
    name: str
    count: int
    conversion_from_previous_percent: float | None


class Funnel(Schema):
    context: Context
    cohort_count: int
    stages: list[FunnelStage]
    conversion_percent: float | None
    updated_at: datetime | None


class DealOut(Schema):
    id: UUID
    external_id: str | None
    customer_id: UUID
    customer_name: str
    product_id: UUID | None
    department_id: UUID
    campaign_id: UUID | None
    channel: str
    segment: str
    stage: Literal["new", "qualified", "proposal", "won", "lost"]
    expected_amount: float
    currency: Literal["BYN"]
    order_id: UUID | None
    created_at: datetime
    updated_at: datetime
