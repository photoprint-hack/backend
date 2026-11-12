"""Database-backed read-only simulations of the five external sources."""

from sqlalchemy import func, select

from app.models import SourceRecord
from app.services.imports import EXCLUDED, REGISTRY
from app.services.serialization import columns


async def records(db, source, page_number, page_size):
    models = REGISTRY[source]
    counts = {
        entity: await db.scalar(select(func.count()).select_from(model)) for entity, model in models.items()
    }
    offset = (page_number - 1) * page_size
    selected = []
    # Stable entity groups and UUID ordering avoid duplicates between pages.
    for entity, model in models.items():
        count = counts[entity]
        if offset >= count:
            offset -= count
            continue
        rows = (
            await db.scalars(select(model).order_by(model.id).offset(offset).limit(page_size - len(selected)))
        ).all()
        selected.extend((entity, row) for row in rows)
        offset = 0
        if len(selected) == page_size:
            break
    ids = {row.id for _, row in selected}
    provenance = (
        (
            await db.scalars(
                select(SourceRecord)
                .where(SourceRecord.source_name == source, SourceRecord.platform_id.in_(ids))
                .order_by(SourceRecord.external_id)
            )
        ).all()
        if ids
        else []
    )
    external_ids = {}
    for item in provenance:
        external_ids.setdefault((item.entity_type, item.platform_id), item.external_id)
    items = []
    for entity, row in selected:
        data = columns(row, exclude=EXCLUDED)
        # Follow the existing import allowlist; identity/security metadata never enters data.
        external_id = external_ids.get((entity, row.id)) or getattr(row, "external_id", None) or str(row.id)
        items.append(
            {
                "entity_type": entity,
                "external_id": external_id,
                "event_at": getattr(row, "updated_at", None) or row.created_at,
                "data": data,
            }
        )
    return items, sum(counts.values())
