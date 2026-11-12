from datetime import UTC, datetime

from sqlalchemy import select, text

from app.core.exceptions import ApiError
from app.core.locks import MARY_INGEST
from app.core.permissions import require_role
from app.models import SourceRecord
from app.models.impact import MaryEvent
from app.services import audit, workflow
from app.services.impact.graph import digest


async def receive(db, payload, user, request):
    require_role(user, {"admin"})
    await db.execute(text(f"SELECT pg_advisory_xact_lock({MARY_INGEST})"))
    result = {"simulated": True, "inserted": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}
    for index, record in enumerate(payload.records):
        try:
            async with db.begin_nested():
                await workflow.active_department(db, record.department_id)
                await workflow.validate_links(db, user, record.department_id, order_id=record.order_id)
                if record.occurred_at > datetime.now(UTC):
                    raise ApiError(422, "VALIDATION_ERROR", "Время события в будущем")
                row = await db.scalar(select(MaryEvent).where(MaryEvent.external_id == record.external_id))
                provenance = await db.scalar(
                    select(SourceRecord).where(
                        SourceRecord.source_name == "mary",
                        SourceRecord.entity_type == "mary_event",
                        SourceRecord.external_id == record.external_id,
                    )
                )
                hashed = digest(record)
                if provenance and (
                    record.occurred_at < provenance.event_at or provenance.content_hash == hashed
                ):
                    result["skipped"] += 1
                    continue
                if row:
                    row.event_type, row.occurred_at = record.event_type, record.occurred_at
                    row.department_id, row.order_id = record.department_id, record.order_id
                    row.metadata_safe = {"channel": record.channel, "simulated": True}
                    counter = "updated"
                else:
                    row = MaryEvent(
                        external_id=record.external_id,
                        event_type=record.event_type,
                        occurred_at=record.occurred_at,
                        department_id=record.department_id,
                        order_id=record.order_id,
                        metadata_safe={"channel": record.channel, "simulated": True},
                    )
                    db.add(row)
                    await db.flush()
                    counter = "inserted"
                if not provenance:
                    provenance = SourceRecord(
                        source_name="mary",
                        entity_type="mary_event",
                        external_id=record.external_id,
                        platform_id=row.id,
                        event_at=record.occurred_at,
                        loaded_at=datetime.now(UTC),
                        processing_status="processed",
                        content_hash=hashed,
                    )
                    db.add(provenance)
                else:
                    provenance.event_at, provenance.content_hash, provenance.loaded_at = (
                        record.occurred_at,
                        hashed,
                        datetime.now(UTC),
                    )
                audit.record(
                    db,
                    "mary.simulated_received",
                    "mary_event",
                    actor=user,
                    object_id=row.id,
                    details={"simulated": True, "event_type": row.event_type},
                    request=request,
                )
                await db.flush()
                result[counter] += 1
        except ApiError as error:
            result["failed"] += 1
            result["errors"].append({"index": index, "code": error.code, "message": error.message})
    return result
