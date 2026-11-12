from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.common import Schema
from app.schemas.shared.query import AnalyticsQuery, SearchQuery


class SupportQuery(SearchQuery, AnalyticsQuery):
    order_id: UUID | None = None
    status: Literal["open", "in_progress", "closed"] | None = None


class SupportOut(Schema):
    id: UUID
    external_id: str | None
    customer_id: UUID
    order_id: UUID | None
    department_id: UUID
    channel: str
    topic: str
    status: Literal["open", "in_progress", "closed"]
    priority: Literal["low", "medium", "high", "critical"]
    created_at: datetime
    first_response_at: datetime | None
    closed_at: datetime | None
    sla_deadline: datetime | None
    resolution: str | None
    cause: str | None
    resolved_within_sla: bool | None
