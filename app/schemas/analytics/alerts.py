from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.analytics.metrics import Kpi
from app.schemas.common import Schema, TextValue
from app.schemas.shared.query import AnalyticsQuery, SearchQuery
from app.schemas.shared.references import NamedObject


class AlertsQuery(SearchQuery, AnalyticsQuery):
    status: Literal["active", "acknowledged", "resolved"] | None = None
    severity: Literal["critical"] | None = None
    metric_code: str | None = None
    has_decision: bool | None = None


class AlertPatch(Schema):
    status: Literal["active", "acknowledged", "resolved"]
    comment: TextValue | None = None


class AlertOut(Schema):
    id: UUID
    created_at: datetime
    updated_at: datetime
    metric_value_id: UUID | None
    metric_code: str
    department_id: UUID | None
    product_id: UUID | None
    period_start: date
    period_end: date
    title: str
    description: str
    deviation_percent: float | None
    actual: float | None
    target: float | None
    opening_actual: float | None
    opening_target: float | None
    severity: Literal["critical"]
    status: Literal["active", "acknowledged", "resolved"]
    allowed_actions: list[str]
    metric_name: str | None = None
    department_name: str | None = None
    product_name: str | None = None


class AlertCause(Schema):
    text: str
    confirmed: bool


class AlertOrder(Schema):
    id: UUID
    label: str
    amount: float | None


class AlertCard(Schema):
    causes: list[AlertCause] = Field(default_factory=list)
    related_orders: list[AlertOrder] = Field(default_factory=list)
    alert: AlertOut
    metric: Kpi
    decisions: list[NamedObject]
    tasks: list[NamedObject]
    decisions_url: str
    tasks_url: str
    breakdown_url: str
