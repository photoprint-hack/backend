import hashlib
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.permissions import READ_ROLES, department_scope, require_role
from app.models import CapacityPlan, ForecastRecord, Order, SourceSyncRun


async def compute(db, user, department_id=None, product_id=None, *, persist=False):
    require_role(user, READ_ROLES)
    department = department_scope(user, department_id)
    zone = ZoneInfo(get_settings().report_timezone)
    today = datetime.now(zone).date()
    monday = today - timedelta(days=today.weekday())
    history_start = monday - timedelta(weeks=4)
    lo = datetime.combine(history_start, time.min, zone)
    hi = datetime.combine(monday, time.min, zone)

    def scoped(stmt, model):
        if department:
            stmt = stmt.where(model.department_id == department)
        if product_id:
            stmt = stmt.where(model.product_id == product_id)
        return stmt

    source = await db.scalar(
        select(SourceSyncRun.id)
        .where(SourceSyncRun.source_name == "erp", SourceSyncRun.status.in_(["success", "partial_success"]))
        .limit(1)
    )
    earliest = await db.scalar(
        scoped(select(func.min(Order.created_at)).where(Order.status != "cancelled"), Order)
    )
    enough = source is not None and earliest is not None and earliest.astimezone(zone).date() <= history_start
    total = await db.scalar(
        scoped(
            select(func.sum(Order.quantity * Order.standard_hours_per_unit)).where(
                Order.status != "cancelled", Order.created_at >= lo, Order.created_at < hi
            ),
            Order,
        )
    )
    demand = (total or Decimal(0)) / 4 if enough else None
    demanded_pairs = set(
        (
            await db.execute(
                scoped(
                    select(Order.department_id, Order.product_id)
                    .where(Order.status != "cancelled", Order.created_at >= lo, Order.created_at < hi)
                    .distinct(),
                    Order,
                )
            )
        ).all()
    )
    start = monday + timedelta(weeks=1)
    plans = (
        await db.scalars(
            scoped(
                select(CapacityPlan).where(
                    CapacityPlan.plan_date >= start, CapacityPlan.plan_date < start + timedelta(weeks=4)
                ),
                CapacityPlan,
            )
        )
    ).all()
    expected_pairs = demanded_pairs | {(p.department_id, p.product_id) for p in plans}
    now = datetime.now(UTC)
    items = []
    first = None
    for i in range(4):
        left = start + timedelta(weeks=i)
        right = left + timedelta(days=6)
        selected = [p for p in plans if left <= p.plan_date <= right]
        pairs = {(p.department_id, p.product_id) for p in selected}
        complete = (
            bool(pairs)
            and pairs == expected_pairs
            and all(
                len({p.plan_date for p in selected if (p.department_id, p.product_id) == pair}) == 7
                for pair in pairs
            )
        )
        capacity = sum((p.available_hours for p in selected), Decimal(0)) if complete else None
        ready = demand is not None and capacity is not None
        deficit = max(demand - capacity, Decimal(0)) if ready else None
        reserve = max(capacity - demand, Decimal(0)) if ready else None
        item = {
            "week_start": left,
            "week_end": right,
            "demand": float(round(demand, 4)) if demand is not None else None,
            "available_capacity": float(round(capacity, 4)) if capacity is not None else None,
            "deficit": float(round(deficit, 4)) if deficit is not None else None,
            "reserve": float(round(reserve, 4)) if reserve is not None else None,
            "utilization_percent": float(round(demand / capacity * 100, 2)) if ready and capacity else None,
            "is_deficit": deficit > 0 if ready else None,
            "status": "deficit" if ready and deficit > 0 else "normal" if ready else "no_data",
        }
        if item["is_deficit"] and first is None:
            first = left
        items.append(item)
    reason = (
        None
        if all(item["status"] != "no_data" for item in items)
        else "Недостаточно четырёх недель истории или полного будущего плана мощности"
    )
    if persist:
        key = int.from_bytes(
            hashlib.sha256(f"forecast:{today}:{department}:{product_id}".encode()).digest()[:8], signed=True
        )
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        for item in items:
            record = await db.scalar(
                select(ForecastRecord).where(
                    ForecastRecord.as_of == today,
                    ForecastRecord.period_start == item["week_start"],
                    ForecastRecord.department_id.is_(None)
                    if department is None
                    else ForecastRecord.department_id == department,
                    ForecastRecord.product_id.is_(None)
                    if product_id is None
                    else ForecastRecord.product_id == product_id,
                )
            )
            if record is None:
                record = ForecastRecord(
                    as_of=today,
                    period_start=item["week_start"],
                    period_end=item["week_end"],
                    department_id=department,
                    product_id=product_id,
                )
                db.add(record)
            for field, target in [
                ("demand", "demand"),
                ("available_capacity", "available_capacity"),
                ("deficit", "deficit"),
                ("reserve", "reserve"),
                ("status", "status"),
            ]:
                setattr(record, field, item[target])
            record.method = "four_week_average"
            record.reason = reason
            record.calculated_at = now
    return {
        "status": "ready" if reason is None else "no_data",
        "reason": reason,
        "method": "four_week_average",
        "unit": "standard_hour",
        "as_of": today,
        "generated_at": now,
        "department_id": department,
        "product_id": product_id,
        "horizon_weeks": 4,
        "history_from": history_start,
        "history_to": monday - timedelta(days=1),
        "items": items,
        "first_deficit_week": first,
    }
