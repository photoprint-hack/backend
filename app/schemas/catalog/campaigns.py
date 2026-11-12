from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.common import Schema
from app.schemas.shared.query import DateRange, SearchQuery


class CampaignsQuery(SearchQuery, DateRange):
    department_id: UUID | None = None
    channel: str | None = None


class CampaignOut(Schema):
    id: UUID
    external_id: str | None
    name: str
    channel: str
    segment: str
    budget: float | None
    currency: Literal["BYN"]
    started_at: datetime
    ended_at: datetime | None
    created_at: datetime
