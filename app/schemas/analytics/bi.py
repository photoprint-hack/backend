from datetime import datetime

from app.schemas.analytics.metrics import Context
from app.schemas.common import Schema


class BIEmbed(Schema):
    embed_url: str
    expires_at: datetime
    context: Context
