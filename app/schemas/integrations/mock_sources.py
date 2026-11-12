from datetime import datetime
from typing import Any, Literal

from app.schemas.common import Schema

MockSource = Literal["crm", "erp", "finance", "support", "hr"]


class MockRecord(Schema):
    entity_type: str
    external_id: str
    event_at: datetime
    data: dict[str, Any]
