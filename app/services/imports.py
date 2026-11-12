import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

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
from app.services import analytics, audit
from app.services.order_links import OrderDealLinkError, validate_import_links
from app.services.serialization import columns

REGISTRY = {
    "crm": {"customer": Customer, "campaign": Campaign, "deal": Deal, "deal_event": DealEvent},
    "erp": {
        "department": Department,
        "product": Product,
        "order": Order,
        "order_event": OrderEvent,
        "production_record": ProductionRecord,
        "capacity_plan": CapacityPlan,
    },
    "finance": {"finance_record": FinanceRecord},
    "support": {"support_interaction": SupportInteraction},
    "hr": {"hr_snapshot": HRSnapshot},
}
TABLES = {model.__tablename__: model for entities in REGISTRY.values() for model in entities.values()}
EXCLUDED = {"id", "updated_at", "external_id", "source_system", "version", "actor_id"}


class RecordError(Exception):
    def __init__(self, code, message, fields=None):
        self.code = code
        self.message = message
        self.fields = fields or {}


def scalar(column, value):
    if value is None:
        if column.nullable:
            return None
        raise RecordError(
            "invalid_values", "Обязательное поле не может быть null", {column.key: "Не допускается null"}
        )
    kind = column.type.python_type
    try:
        if kind is datetime:
            result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
            if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
                raise ValueError()
            return result
        if kind is date:
            result = date.fromisoformat(value) if isinstance(value, str) else value
            if type(result) is not date:
                raise ValueError()
            return result
        if kind is UUID:
            return UUID(str(value))
        if kind is bool:
            if not isinstance(value, bool):
                raise ValueError()
            return value
        if kind is int:
            if isinstance(value, bool) or Decimal(str(value)) != int(value) or int(value) < 0:
                raise ValueError()
            return int(value)
        if kind is Decimal:
            result = Decimal(str(value))
            if not result.is_finite() or result < 0:
                raise ValueError()
            scale = column.type.scale
            if result != result.quantize(Decimal(1).scaleb(-scale)):
                raise ValueError()
            if result >= Decimal(10) ** (column.type.precision - scale):
                raise ValueError()
            return result
        if kind is str:
            if not isinstance(value, str):
                raise ValueError()
            limit = getattr(column.type, "length", None) or 5000
            result = value.strip()
            if len(result) > limit or not result:
                raise ValueError()
            return result
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        raise RecordError(
            "invalid_values", "Некорректное значение поля", {column.key: "Неверный тип, формат или диапазон"}
        ) from None
    raise RecordError("invalid_values", "Неподдерживаемое поле", {column.key: "Неподдерживаемый тип"})


async def resolve(db, column, value):
    if isinstance(value, dict):
        if set(value) != {"source", "entity_type", "external_id"} or not all(
            isinstance(v, str) for v in value.values()
        ):
            raise RecordError(
                "broken_relations",
                "Неверный формат внешней ссылки",
                {column.key: "Требуются source/entity_type/external_id"},
            )
        model = REGISTRY.get(value["source"], {}).get(value["entity_type"])
        expected = next(iter(column.foreign_keys)).column.table.name
        if model is None or model.__tablename__ != expected:
            raise RecordError("broken_relations", "Неверный тип внешней ссылки")
        provenance = await db.scalar(
            select(SourceRecord).where(
                SourceRecord.source_name == value["source"],
                SourceRecord.entity_type == value["entity_type"],
                SourceRecord.external_id == value["external_id"],
            )
        )
        if not provenance or not provenance.platform_id:
            raise RecordError(
                "broken_relations",
                "Связанная запись ещё не загружена",
                {column.key: "Не найден внешний идентификатор"},
            )
        return provenance.platform_id
    identifier = scalar(column, value)
    if identifier is not None and column.foreign_keys:
        target = TABLES.get(next(iter(column.foreign_keys)).column.table.name)
        if target is None or await db.get(target, identifier) is None:
            raise RecordError(
                "broken_relations", "Связанная запись не найдена", {column.key: "Неизвестный UUID"}
            )
    return identifier


async def normalize(db, model, data, event_at):
    allowed = {c.key: c for c in inspect(model).columns if c.key not in EXCLUDED}
    extra = set(data) - set(allowed)
    if extra:
        raise RecordError(
            "invalid_values",
            "Неизвестные поля",
            {key: "Поле не разрешено для импорта" for key in sorted(extra)},
        )
    result = {}
    for key, column in allowed.items():
        if key in data:
            result[key] = (
                await resolve(db, column, data[key]) if column.foreign_keys else scalar(column, data[key])
            )
        elif key == "created_at":
            result[key] = event_at
        elif column.nullable:
            result[key] = None
        elif column.default is None and column.server_default is None:
            raise RecordError("missing_fields", "Отсутствует обязательное поле", {key: "Поле обязательно"})
    if hasattr(model, "currency") and result.get("currency", "BYN") != "BYN":
        raise RecordError("invalid_values", "Валюта MVP — BYN")
    allowed_enums = {
        "customer_type": {"b2b", "b2c"},
        "priority": {"low", "medium", "high", "critical"},
        "stage": {"new", "qualified", "proposal", "won", "lost"},
        "moderation_status": {"pending", "approved", "rejected", "revision_required"},
        "production_status": {"queued", "in_progress", "completed", "blocked"},
        "delivery_status": {"not_started", "in_transit", "delivered", "delayed", "returned"},
    }
    for field, choices in allowed_enums.items():
        if field in result and result[field] is not None and result[field] not in choices:
            raise RecordError(
                "invalid_values", "Неизвестное значение перечисления", {field: "Недопустимое значение"}
            )
    if model is Order and result.get("completed_at") and result["completed_at"] > datetime.now(UTC):
        raise RecordError("invalid_values", "Завершение заказа не может быть в будущем")
    if model is DealEvent and result["new_stage"] not in {"new", "qualified", "proposal", "won", "lost"}:
        raise RecordError("invalid_values", "Неизвестная стадия сделки")
    if model is Order and result.get("status") == "completed" and not result.get("completed_at"):
        raise RecordError("missing_fields", "Завершённому заказу требуется completed_at")
    if model is Deal:
        if result.get("stage") == "won" and not result.get("order_id"):
            raise RecordError("broken_relations", "Выигранная сделка должна быть связана с заказом")
    order_id = result.get("order_id")
    if order_id and model in {FinanceRecord, ProductionRecord, SupportInteraction}:
        order = await db.get(Order, order_id)
        if model is SupportInteraction and result.get("customer_id") != order.customer_id:
            raise RecordError("broken_relations", "Клиент не соответствует заказу")
        if model in {FinanceRecord, ProductionRecord}:
            if result.get("product_id") and result["product_id"] != order.product_id:
                raise RecordError("broken_relations", "Продукт не соответствует заказу")
            result["product_id"] = order.product_id
    return result


async def import_records(db, source, records, user, request=None):
    now = datetime.now(UTC)
    run = SourceSyncRun(
        source_name=source,
        status="running",
        started_at=now,
        records_received=len(records),
        records_inserted=0,
        records_updated=0,
        records_skipped=0,
        records_failed=0,
        errors=[],
    )
    db.add(run)
    await db.flush()
    audit.record(
        db,
        "integration.started",
        "integration",
        actor=user,
        object_id=run.id,
        details={"source": source, "records": len(records)},
        request=request,
    )
    await db.commit()
    seen = set()
    errors = []
    inserted = updated = skipped = 0
    for index, record in enumerate(records):
        entity = record.get("entity_type")
        external = record.get("external_id")
        try:
            if set(record) != {"entity_type", "external_id", "event_at", "data"}:
                raise RecordError(
                    "missing_fields", "Запись должна содержать entity_type/external_id/event_at/data"
                )
            if (
                not isinstance(entity, str)
                or not isinstance(external, str)
                or not 1 <= len(external) <= 200
                or not isinstance(record["data"], dict)
            ):
                raise RecordError("invalid_values", "Некорректный заголовок записи")
            model = REGISTRY[source].get(entity)
            if model is None:
                raise RecordError("invalid_values", "Тип записи не поддерживается источником")
            if (entity, external) in seen:
                raise RecordError("duplicates", "Повторный внешний идентификатор внутри пакета")
            try:
                event_at = datetime.fromisoformat(record["event_at"].replace("Z", "+00:00"))
            except (ValueError, TypeError, AttributeError):
                raise RecordError(
                    "invalid_values", "event_at должен быть ISO 8601 со временем и часовым поясом"
                ) from None
            if event_at.tzinfo is None:
                raise RecordError("invalid_values", "event_at требует часовой пояс")
            async with db.begin_nested():
                await db.execute(text("SELECT pg_advisory_xact_lock(178901234)"))
                values = await normalize(db, model, record["data"], event_at)
                digest = hashlib.sha256(
                    json.dumps(jsonable_encoder(values), sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                provenance = await db.scalar(
                    select(SourceRecord)
                    .where(
                        SourceRecord.source_name == source,
                        SourceRecord.entity_type == entity,
                        SourceRecord.external_id == external,
                    )
                    .with_for_update()
                )
                if provenance and (provenance.content_hash == digest or event_at < provenance.event_at):
                    skipped += 1
                else:
                    obj = await db.get(model, provenance.platform_id) if provenance else None
                    if provenance and not obj:
                        raise RecordError(
                            "broken_relations", "Исходная запись указывает на отсутствующий объект"
                        )
                    before = columns(obj) if obj else None
                    try:
                        await validate_import_links(db, model, values, obj)
                    except OrderDealLinkError as exc:
                        raise RecordError("broken_relations", str(exc)) from None
                    if obj:
                        if (
                            model is Order
                            and obj.status in {"completed", "cancelled"}
                            and values.get("status") != obj.status
                        ):
                            raise RecordError(
                                "invalid_values", "Нельзя переоткрывать терминальный заказ импортом"
                            )
                        for key, value in values.items():
                            setattr(obj, key, value)
                        if hasattr(obj, "version"):
                            obj.version += 1
                        if hasattr(obj, "updated_at"):
                            obj.updated_at = datetime.now(UTC)
                    else:
                        obj = model(**values)
                        if hasattr(model, "external_id"):
                            obj.external_id = external
                        if hasattr(model, "source_system"):
                            obj.source_system = source
                        db.add(obj)
                    await db.flush()
                    if not provenance:
                        provenance = SourceRecord(
                            source_name=source,
                            entity_type=entity,
                            external_id=external,
                            platform_id=obj.id,
                            event_at=event_at,
                            loaded_at=datetime.now(UTC),
                            processing_status="success",
                            content_hash=digest,
                        )
                        db.add(provenance)
                        inserted += 1
                    else:
                        provenance.event_at = event_at
                        provenance.loaded_at = datetime.now(UTC)
                        provenance.content_hash = digest
                        updated += 1
                    if model is Order:
                        db.add(
                            OrderEvent(
                                order_id=obj.id,
                                event_type="source_imported",
                                department_id=obj.department_id,
                                source_system=source,
                                old_status=before.get("status") if before else None,
                                new_status=obj.status,
                                result="Заказ обновлён из mock-источника",
                                occurred_at=event_at,
                            )
                        )
                        audit.record(
                            db,
                            "order.updated" if before else "order.created",
                            "order",
                            actor=user,
                            object_id=obj.id,
                            object_name=obj.order_number,
                            old=before,
                            new=columns(obj),
                            request=request,
                        )
            await db.commit()
            seen.add((entity, external))
        except (RecordError, IntegrityError) as exc:
            # Savepoint rollback preserves previous valid records and their audits.
            await db.commit()
            code = (
                exc.code
                if isinstance(exc, RecordError)
                else "broken_relations"
                if getattr(exc.orig, "sqlstate", None) == "23503"
                else "invalid_values"
            )
            errors.append(
                {
                    "index": index,
                    "entity_type": entity if isinstance(entity, str) else None,
                    "external_id": external if isinstance(external, str) else None,
                    "code": code,
                    "message": exc.message
                    if isinstance(exc, RecordError)
                    else "Нарушение ограничений записи",
                    "fields": exc.fields if isinstance(exc, RecordError) else {},
                }
            )
    run.records_inserted = inserted
    run.records_updated = updated
    run.records_skipped = skipped
    run.records_failed = len(errors)
    run.errors = errors
    run.status = (
        "partial_success" if errors and inserted + updated + skipped else "failed" if errors else "success"
    )
    run.finished_at = datetime.now(UTC)
    audit.record(
        db,
        "integration.finished",
        "integration",
        actor=user,
        object_id=run.id,
        status="failure" if run.status == "failed" else "success",
        details={
            "source": source,
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "failed": len(errors),
        },
        request=request,
    )
    await db.commit()
    run_id = run.id
    if inserted + updated:
        try:
            await analytics.recalculate(db, user, request)
            await db.commit()
            run.recalculation_status = "success"
        except Exception:
            await db.rollback()
            run = await db.get(SourceSyncRun, run_id)
            run.recalculation_status = "failed"
            run.recalculation_error = "Пересчёт не завершён; принятые записи сохранены"
        await db.commit()
    return run
