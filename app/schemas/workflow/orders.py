from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.schemas.common import Hours, Money, Schema
from app.schemas.shared.query import AnalyticsQuery, SearchQuery
from app.schemas.shared.references import UserRef
from app.schemas.workflow.common import VersionedPatch

OrderStatus = Literal["new", "in_progress", "completed", "cancelled"]


class OrdersQuery(SearchQuery, AnalyticsQuery):
    status: OrderStatus | None = None
    customer_id: UUID | None = None
    campaign_id: UUID | None = None
    channel: str | None = None


class OrderCreate(Schema):
    customer_id: UUID
    product_id: UUID
    department_id: UUID
    quantity: Annotated[int, Field(ge=1)]
    amount: Money
    currency: Literal["BYN"] = "BYN"
    channel: Annotated[str, Field(min_length=1, max_length=100)]
    due_at: AwareDatetime
    campaign_id: UUID | None = None
    crm_deal_id: UUID | None = None


class OrderPatch(VersionedPatch):
    quantity: Annotated[int, Field(ge=1)] | None = None
    amount: Money | None = None
    channel: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    due_at: AwareDatetime | None = None
    status: OrderStatus | None = None
    completed_at: AwareDatetime | None = None
    moderation_status: Literal["pending", "approved", "rejected", "revision_required"] | None = None
    production_status: Literal["queued", "in_progress", "completed", "blocked"] | None = None
    delivery_status: Literal["not_started", "in_transit", "delivered", "delayed", "returned"] | None = None


class OrderOut(Schema):
    id: UUID
    external_id: str | None
    order_number: str
    customer_id: UUID
    customer_name: str
    product_id: UUID
    product_name: str
    department_id: UUID
    department_name: str
    campaign_id: UUID | None
    crm_deal_id: UUID | None
    quantity: int
    standard_hours_per_unit: Hours
    amount: Money
    currency: Literal["BYN"]
    channel: str
    status: OrderStatus
    moderation_status: str
    production_status: str
    delivery_status: str
    has_defect: bool
    source_system: str
    created_at: datetime
    due_at: datetime
    completed_at: datetime | None
    updated_at: datetime
    version: int
    allowed_actions: list[str]


class OrderEventOut(Schema):
    id: UUID
    order_id: UUID
    event_type: str
    old_status: str | None
    new_status: str | None
    department_id: UUID | None
    actor: UserRef | None
    source_system: str
    description: str | None
    result: str | None
    cause: str | None
    occurred_at: datetime
    created_at: datetime
