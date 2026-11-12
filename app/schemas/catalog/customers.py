from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.common import Schema
from app.schemas.shared.query import DateRange, SearchQuery


class CustomersQuery(SearchQuery, DateRange):
    department_id: UUID | None = None
    segment: str | None = None
    customer_type: Literal["b2b", "b2c"] | None = None


class CustomerOut(Schema):
    id: UUID
    external_id: str | None
    name: str
    customer_type: Literal["b2b", "b2c"]
    segment: str
    acquisition_channel: str
    first_order_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CustomerCard(Schema):
    customer: CustomerOut
    orders_url: str
