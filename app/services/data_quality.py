from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text

from app.models import DataQualityIssue, DataQualityRun, FinanceRecord, Order, SourceRecord, SourceSyncRun
from app.services.analytics import D, number, period
from app.services.audit import record

SOURCES = {
    "crm": "CRM",
    "erp": "ERP / производство",
    "finance": "Финансы",
    "support": "Поддержка",
    "hr": "Персонал",
}


async def source_status(db, source):
    latest = await db.scalar(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == source)
        .order_by(SourceSyncRun.started_at.desc(), SourceSyncRun.id)
        .limit(1)
    )
    success = await db.scalar(
        select(SourceSyncRun.finished_at)
        .where(SourceSyncRun.source_name == source, SourceSyncRun.status.in_(["success", "partial_success"]))
        .order_by(SourceSyncRun.finished_at.desc())
        .limit(1)
    )
    count = await db.scalar(
        select(func.count()).select_from(SourceRecord).where(SourceRecord.source_name == source)
    )
    errors = latest.errors if latest else []
    missing = sum(e.get("code") == "missing_fields" for e in errors)
    duplicates = sum(e.get("code") == "duplicates" for e in errors)
    stale = success is not None and datetime.now(UTC) - success > timedelta(hours=24)
    state = (
        "not_loaded"
        if success is None
        else "error"
        if latest and latest.status == "failed"
        else "warning"
        if stale or latest and latest.records_failed
        else "healthy"
    )
    return {
        "id": source,
        "code": source,
        "name": SOURCES[source],
        "source_type": "mock_api",
        "status": state,
        "last_sync_at": success,
        "last_success_at": success,
        "last_attempt_at": latest.started_at if latest else None,
        "is_stale": stale,
        "records_count": count,
        "records_received": latest.records_received if latest else 0,
        "records_inserted": latest.records_inserted if latest else 0,
        "records_updated": latest.records_updated if latest else 0,
        "records_skipped": latest.records_skipped if latest else 0,
        "records_failed": latest.records_failed if latest else 0,
        "missing_count": missing,
        "duplicate_count": duplicates,
        "error_count": latest.records_failed if latest else 0,
    }


async def reconciliation(db, query):
    start, end, lo, hi = period(query)
    dept = query.department_id
    product = query.product_id
    orders = select(func.sum(Order.amount)).where(
        Order.status == "completed", Order.completed_at >= lo, Order.completed_at < hi
    )
    finances = select(func.sum(FinanceRecord.amount)).where(
        FinanceRecord.record_type == "revenue",
        FinanceRecord.record_date >= start,
        FinanceRecord.record_date <= end,
    )
    if dept:
        orders = orders.where(Order.department_id == dept)
        finances = finances.where(FinanceRecord.department_id == dept)
    if product:
        orders = orders.where(Order.product_id == product)
        finances = finances.where(FinanceRecord.product_id == product)
    ready = (
        await db.scalar(
            select(func.count(func.distinct(SourceSyncRun.source_name))).where(
                SourceSyncRun.source_name.in_(["erp", "finance"]),
                SourceSyncRun.status.in_(["success", "partial_success"]),
            )
        )
        == 2
    )
    erp = (await db.scalar(orders) or D(0)) if ready else None
    finance = (await db.scalar(finances) or D(0)) if ready else None
    difference = erp - finance if ready else None
    percent = abs(difference) / abs(erp) * 100 if ready and erp else D(0) if ready and finance == 0 else None
    status = (
        "no_data"
        if not ready
        else "normal"
        if abs(difference) <= D("0.01")
        else "critical"
        if percent is None or percent > 1
        else "warning"
    )
    return {
        "context": {
            "date_from": start,
            "date_to": end,
            "department_id": dept,
            "product_id": product,
            "ignored_filters": [],
        },
        "currency": "BYN",
        "period": {"date_from": start, "date_to": end},
        "source_a": {"name": "ERP", "amount": number(erp, "BYN")},
        "source_b": {"name": "Finance", "amount": number(finance, "BYN")},
        "erp_revenue": number(erp, "BYN"),
        "finance_revenue": number(finance, "BYN"),
        "difference": number(difference, "BYN"),
        "difference_percent": number(percent),
        "status": status,
        "reason": None if ready else "ERP или финансовый источник ещё не загружен",
        "checked_at": datetime.now(UTC),
    }


async def check(db, actor, source=None, request=None):
    from types import SimpleNamespace

    await db.execute(text("SELECT pg_advisory_xact_lock(178901235)"))
    selected = [source] if source else list(SOURCES)
    now = datetime.now(UTC)
    issues = []
    checks = 0
    for code in selected:
        state = await source_status(db, code)
        checks += 5
        if state["status"] == "not_loaded" or state["is_stale"]:
            issues.append(
                (
                    f"{code}:stale_source",
                    code,
                    "stale_source",
                    "critical",
                    "Источник не загружен или обновлялся более 24 часов назад",
                    1,
                    {},
                )
            )
        latest = await db.scalar(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == code)
            .order_by(SourceSyncRun.started_at.desc())
            .limit(1)
        )
        if latest:
            grouped = Counter(error.get("code", "invalid_values") for error in latest.errors)
            for kind, amount in grouped.items():
                check_type = (
                    kind
                    if kind in {"missing_fields", "duplicates", "invalid_values", "broken_relations"}
                    else "invalid_values"
                )
                issues.append(
                    (
                        f"{code}:import:{kind}",
                        code,
                        check_type,
                        "warning" if kind == "duplicates" else "critical",
                        f"Ошибки последней загрузки: {kind}",
                        amount,
                        {"run_id": str(latest.id)},
                    )
                )
    from sqlalchemy import String, Text, inspect, or_

    from app.models import Deal, DealEvent
    from app.services.imports import REGISTRY

    for code in selected:
        missing_fields = 0
        broken = 0
        for entity, model in REGISTRY[code].items():
            broken += await db.scalar(
                select(func.count())
                .select_from(SourceRecord)
                .outerjoin(model, model.id == SourceRecord.platform_id)
                .where(
                    SourceRecord.source_name == code, SourceRecord.entity_type == entity, model.id.is_(None)
                )
            )
            empty_conditions = [
                func.length(func.trim(getattr(model, column.key))) == 0
                for column in inspect(model).columns
                if isinstance(column.type, (String, Text)) and not column.nullable
            ]
            if empty_conditions:
                missing_fields += await db.scalar(
                    select(func.count()).select_from(model).where(or_(*empty_conditions))
                )
            checks += 2
        if code == "crm":
            broken += await db.scalar(
                select(func.count()).select_from(Deal).where(Deal.stage == "won", Deal.order_id.is_(None))
            )
            invalid = await db.scalar(
                select(func.count())
                .select_from(DealEvent)
                .where(DealEvent.new_stage.not_in(["new", "qualified", "proposal", "won", "lost"]))
            )
            if invalid:
                issues.append(
                    (
                        "crm:invalid_stage",
                        "crm",
                        "invalid_values",
                        "critical",
                        "Неизвестные стадии CRM",
                        invalid,
                        {},
                    )
                )
        if missing_fields:
            issues.append(
                (
                    f"{code}:persisted_missing",
                    code,
                    "missing_fields",
                    "critical",
                    "Пустые обязательные поля в сохранённых данных",
                    missing_fields,
                    {},
                )
            )
        if broken:
            issues.append(
                (
                    f"{code}:persisted_relations",
                    code,
                    "broken_relations",
                    "critical",
                    "Нарушены связи или выигранная сделка не связана с заказом",
                    broken,
                    {},
                )
            )
    if source in (None, "erp", "finance"):
        checks += 1
        result = await reconciliation(
            db, SimpleNamespace(date_from=None, date_to=None, department_id=None, product_id=None)
        )
        if result["status"] in {"warning", "critical"}:
            issues.append(
                (
                    "finance:financial_reconciliation",
                    "finance",
                    "financial_reconciliation",
                    result["status"],
                    "Расхождение выручки ERP и финансовой витрины",
                    1,
                    {
                        "erp": result["erp_revenue"],
                        "finance": result["finance_revenue"],
                        "difference": result["difference"],
                        "difference_percent": result["difference_percent"],
                    },
                )
            )
    active = {x[0] for x in issues}
    opened = 0
    resolved = 0
    existing = (
        await db.scalars(
            select(DataQualityIssue).where(
                or_(
                    DataQualityIssue.source_name.in_(selected),
                    DataQualityIssue.fingerprint == "finance:financial_reconciliation",
                )
                if source == "erp"
                else DataQualityIssue.source_name.in_(selected)
            )
        )
    ).all()
    for previous in existing:
        if previous.status == "open" and previous.fingerprint not in active:
            previous.status = "resolved"
            previous.checked_at = now
            resolved += 1
    for fingerprint, code, kind, severity, description, count, details in issues:
        obj = next((x for x in existing if x.fingerprint == fingerprint), None)
        if obj is None:
            obj = DataQualityIssue(
                fingerprint=fingerprint,
                source_name=code,
                check_type=kind,
                severity=severity,
                description=description,
                affected_records=count,
                status="open",
                checked_at=now,
                details=details,
            )
            db.add(obj)
            opened += 1
        else:
            if obj.status != "open":
                opened += 1
            obj.status = "open"
            obj.severity = severity
            obj.description = description
            obj.affected_records = count
            obj.details = details
            obj.checked_at = now
    run = DataQualityRun(
        checked_at=now, source_name=source, checks_run=checks, issues_opened=opened, issues_resolved=resolved
    )
    db.add(run)
    await db.flush()
    record(
        db,
        "data_quality.checked",
        "data_quality",
        actor=actor,
        object_id=run.id,
        details={"checks_run": checks, "issues_opened": opened, "issues_resolved": resolved},
        request=request,
    )
    return {
        "run_id": run.id,
        "checked_at": now,
        "checks_run": checks,
        "issues_opened": opened,
        "issues_resolved": resolved,
    }
