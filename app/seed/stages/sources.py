import hashlib

from sqlalchemy import select

from app.models import (
    Campaign,
    CapacityPlan,
    Customer,
    Deal,
    DealEvent,
    Department,
    FinanceRecord,
    HRSnapshot,
    Order,
    OrderEvent,
    Product,
    ProductionRecord,
    SourceRecord,
    SourceSyncRun,
    SupportInteraction,
)
from app.seed.context import SeedContext


async def seed_sources(ctx: SeedContext):
    db = ctx.db
    now = ctx.now
    restore = ctx.restore
    add = ctx.add
    from fastapi.encoders import jsonable_encoder
    from sqlalchemy import func

    from app.services.serialization import columns

    source_models = {
        "crm": [(Customer, "customer"), (Campaign, "campaign"), (Deal, "deal"), (DealEvent, "deal_event")],
        "erp": [
            (Department, "department"),
            (Product, "product"),
            (Order, "order"),
            (OrderEvent, "order_event"),
            (ProductionRecord, "production_record"),
            (CapacityPlan, "capacity_plan"),
        ],
        "finance": [(FinanceRecord, "finance_record")],
        "support": [(SupportInteraction, "support_interaction")],
        "hr": [(HRSnapshot, "hr_snapshot")],
    }
    for source, mappings in source_models.items():
        for model, entity in mappings:
            for obj in (await db.scalars(select(model))).all():
                key = f"provenance:{source}:{entity}:{obj.id}"
                data = jsonable_encoder(columns(obj))
                import json

                digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
                add(
                    SourceRecord,
                    key,
                    source_name=source,
                    entity_type=entity,
                    external_id=obj.external_id
                    if hasattr(obj, "external_id") and obj.external_id
                    else str(obj.id),
                    platform_id=obj.id,
                    event_at=obj.created_at,
                    loaded_at=now,
                    processing_status="success",
                    content_hash=digest,
                )
        await db.flush()
        count = await db.scalar(
            select(func.count()).select_from(SourceRecord).where(SourceRecord.source_name == source)
        )
        exists = await db.scalar(
            select(SourceSyncRun.id)
            .where(SourceSyncRun.source_name == source, SourceSyncRun.status == "success")
            .limit(1)
        )
        if not exists or restore:
            db.add(
                SourceSyncRun(
                    source_name=source,
                    status="success",
                    started_at=now,
                    finished_at=now,
                    records_received=count,
                    records_inserted=count,
                    records_updated=0,
                    records_skipped=0,
                    records_failed=0,
                    errors=[],
                )
            )
    await db.flush()
