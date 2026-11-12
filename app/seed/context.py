from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.locks import RECALCULATION
from app.models import (
    Campaign,
    CapacityPlan,
    Customer,
    Deal,
    DealEvent,
    Department,
    FinanceRecord,
    HRSnapshot,
    Metric,
    MetricTarget,
    Order,
    OrderEvent,
    Product,
    ProductionRecord,
    SourceRecord,
    SupportInteraction,
    User,
)


def identifier(value):
    return uuid5(NAMESPACE_URL, "photoprint:demo:" + value)


@dataclass
class SeedContext:
    db: AsyncSession
    passwords: dict[str, str] = field(repr=False)
    reference: date
    zone: ZoneInfo
    now: datetime
    restore: bool
    known: dict
    restore_objects: dict
    inserted: int = 0
    departments: list = field(default_factory=list)
    people: dict = field(default_factory=dict)
    products: list = field(default_factory=list)
    campaigns: list = field(default_factory=list)
    customers: list = field(default_factory=list)
    orders: list = field(default_factory=list)

    def add(self, model, key, **values):
        known = self.known
        restore = self.restore
        restore_objects = self.restore_objects
        db = self.db
        uid = identifier(key)
        if uid in known[model]:
            if restore and model not in {User, SourceRecord}:
                obj = restore_objects[model][uid]
                old_version = getattr(obj, "version", None)
                for field, value in values.items():
                    if field != "version":
                        setattr(obj, field, value)
                if old_version is not None:
                    obj.version = old_version + 1
            return uid
        db.add(model(id=uid, **values))
        known[model].add(uid)
        self.inserted += 1
        return uid


async def create_context(db, *, passwords, reference=None, restore=False):
    config = get_settings()
    zone = ZoneInfo(config.report_timezone)
    now = datetime.now(UTC)
    reference = reference or datetime.now(zone).date()
    for role in ("admin", "director", "manager", "analyst", "employee"):
        if role not in passwords or not 12 <= len(passwords[role]) <= 128:
            raise ValueError("Provide 12–128-character demo passwords for all five roles")
    await db.execute(text(f"SELECT pg_advisory_xact_lock({RECALCULATION})"))
    # Stable IDs and insert-only seeding preserve existing credentials and user activity.
    known = {
        model: set((await db.scalars(select(model.id))).all())
        for model in (
            Department,
            User,
            Product,
            Campaign,
            Customer,
            Order,
            Deal,
            DealEvent,
            OrderEvent,
            ProductionRecord,
            CapacityPlan,
            FinanceRecord,
            HRSnapshot,
            SupportInteraction,
            Metric,
            MetricTarget,
            SourceRecord,
        )
    }
    restore_objects = (
        {model: {obj.id: obj for obj in (await db.scalars(select(model))).all()} for model in known}
        if restore
        else {}
    )
    return SeedContext(
        db=db,
        passwords=passwords,
        reference=reference,
        zone=zone,
        now=now,
        restore=restore,
        known=known,
        restore_objects=restore_objects,
    )
