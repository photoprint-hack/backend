import calendar
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.permissions import READ_ROLES, department_scope, require_role
from app.models import (
    Alert,
    CapacityPlan,
    FinanceRecord,
    HRSnapshot,
    Metric,
    MetricTarget,
    MetricValue,
    Order,
    ProductionRecord,
    SourceSyncRun,
    SupportInteraction,
)
from app.services.audit import record

D = Decimal
# code, name, unit, source codes, direction, category, default percentage target, formula
DEFINITIONS = [
    (
        "revenue",
        "Оборот",
        "BYN",
        ["erp"],
        "higher_is_better",
        "finance",
        None,
        "SUM(completed_orders.amount)",
    ),
    (
        "gross_margin",
        "Валовая маржа",
        "%",
        ["erp", "finance"],
        "higher_is_better",
        "finance",
        D("35"),
        "(revenue - related_direct_cost) / revenue * 100",
    ),
    (
        "on_time_orders",
        "Заказы в срок",
        "%",
        ["erp"],
        "higher_is_better",
        "production",
        D("95"),
        "on_time_completed_orders / completed_orders * 100",
    ),
    (
        "defect_rate",
        "Доля брака",
        "%",
        ["erp"],
        "lower_is_better",
        "production",
        D("2"),
        "defective_units / produced_units * 100",
    ),
    (
        "new_customers",
        "Новые клиенты",
        "клиентов",
        ["crm", "erp"],
        "higher_is_better",
        "sales",
        None,
        "COUNT(DISTINCT customers_with_first_completed_purchase_in_scope)",
    ),
    (
        "active_customers",
        "Активные клиенты",
        "клиентов",
        ["crm", "erp"],
        "higher_is_better",
        "sales",
        None,
        "COUNT(DISTINCT completed_orders.customer_id)",
    ),
    (
        "repeat_purchase_rate",
        "Повторные покупки",
        "%",
        ["crm", "erp"],
        "higher_is_better",
        "sales",
        D("30"),
        "customers_with_two_completed_orders / active_customers * 100",
    ),
    (
        "support_sla",
        "SLA поддержки",
        "%",
        ["support"],
        "higher_is_better",
        "support",
        D("95"),
        "closed_on_time_with_sla / closed_with_sla * 100",
    ),
    (
        "capacity_utilization",
        "Загрузка мощности",
        "%",
        ["erp"],
        "range",
        "production",
        D("100"),
        "actual_load_hours / planned_capacity_hours * 100",
    ),
    (
        "staffing_coverage",
        "Обеспеченность персоналом",
        "%",
        ["hr"],
        "higher_is_better",
        "hr",
        D("100"),
        "available_headcount / required_headcount * 100",
    ),
    (
        "sales_plan_achievement",
        "Выполнение плана продаж",
        "%",
        ["erp", "finance"],
        "higher_is_better",
        "sales",
        D("100"),
        "completed_revenue / revenue_target * 100",
    ),
    (
        "critical_alerts_count",
        "Критические отклонения",
        "шт.",
        ["system"],
        "none",
        "system",
        None,
        "COUNT(open_critical_alerts)",
    ),
]


def metric_id(code):
    return uuid5(NAMESPACE_URL, "photoprint:metric:" + code)


def period(query):
    zone = ZoneInfo(get_settings().report_timezone)
    today = datetime.now(zone).date()
    start = query.date_from or today.replace(day=1)
    end = query.date_to or today
    if end < start or (end - start).days > 365:
        raise ApiError(422, "VALIDATION_ERROR", "Некорректный период (максимум 366 дней)")
    return (
        start,
        end,
        datetime.combine(start, time.min, zone),
        datetime.combine(end + timedelta(days=1), time.min, zone),
    )


def percentage(numerator, denominator):
    return D(numerator) / D(denominator) * 100 if denominator else None


def classify(actual, target, direction):
    if actual is None:
        return "no_data", None, None
    if direction == "none":
        return ("normal" if actual == 0 else "critical"), None, None
    if direction == "range":
        status = "normal" if D(70) <= actual <= D(100) else "critical" if actual > D(110) else "warning"
        return status, actual, actual - 100
    if target is None:
        return "no_data", None, None
    if target == 0:
        return ("normal" if actual == 0 else "no_data"), None, None
    deviation = (actual - target) / abs(target) * 100
    unfavorable = max(deviation if direction == "lower_is_better" else -deviation, D(0))
    return (
        ("normal" if unfavorable <= 5 else "warning" if unfavorable <= 10 else "critical"),
        actual / target * 100,
        deviation,
    )


def number(value, unit="%"):
    if value is None:
        return None
    if unit in {"шт.", "клиентов"}:
        return int(value)
    return float(D(value).quantize(D("0.01"), rounding=ROUND_HALF_UP))


async def calculate(db, query, user):
    require_role(user, READ_ROLES)
    department = department_scope(user, query.department_id)
    product = query.product_id
    start, end, lo, hi = period(query)
    context = {
        "date_from": start,
        "date_to": end,
        "timezone": get_settings().report_timezone,
        "department_id": department,
        "product_id": product,
        "ignored_filters": [],
    }

    def scope(stmt, model, *, has_product=True):
        if department:
            stmt = stmt.where(model.department_id == department)
        if product and has_product:
            stmt = stmt.where(model.product_id == product)
        return stmt

    order_stmt = scope(
        select(Order).where(Order.status == "completed", Order.completed_at >= lo, Order.completed_at < hi),
        Order,
    )
    orders = (await db.scalars(order_stmt)).all()
    order_ids = {x.id for x in orders}
    productions = (
        await db.scalars(
            scope(
                select(ProductionRecord).where(
                    ProductionRecord.production_date >= start, ProductionRecord.production_date <= end
                ),
                ProductionRecord,
            )
        )
    ).all()
    capacities = (
        await db.scalars(
            scope(
                select(CapacityPlan).where(CapacityPlan.plan_date >= start, CapacityPlan.plan_date <= end),
                CapacityPlan,
            )
        )
    ).all()
    support_stmt = select(SupportInteraction).where(
        SupportInteraction.status == "closed",
        SupportInteraction.closed_at >= lo,
        SupportInteraction.closed_at < hi,
        SupportInteraction.sla_deadline.is_not(None),
    )
    if department:
        support_stmt = support_stmt.where(SupportInteraction.department_id == department)
    if product:
        support_stmt = support_stmt.where(
            SupportInteraction.order_id.in_(select(Order.id).where(Order.product_id == product))
        )
    tickets = (await db.scalars(support_stmt)).all()
    hrs = (
        await db.scalars(
            scope(
                select(HRSnapshot).where(HRSnapshot.snapshot_date <= end), HRSnapshot, has_product=False
            ).order_by(HRSnapshot.snapshot_date)
        )
    ).all()
    latest = {x.department_id: x for x in hrs}
    finance = (
        (
            await db.scalars(
                select(FinanceRecord).where(
                    FinanceRecord.record_type == "direct_cost", FinanceRecord.order_id.in_(order_ids)
                )
            )
        ).all()
        if order_ids
        else []
    )
    first_stmt = scope(
        select(Order.customer_id, func.min(Order.completed_at))
        .where(Order.status == "completed")
        .group_by(Order.customer_id),
        Order,
    )
    firsts = (await db.execute(first_stmt)).all()
    targets = (
        await db.scalars(
            scope(
                select(MetricTarget).where(MetricTarget.plan_date >= start, MetricTarget.plan_date <= end),
                MetricTarget,
            )
        )
    ).all()
    summed = defaultdict(lambda: D(0))
    target_ids = set()
    for row in targets:
        summed[row.metric_id] += row.target_value
        target_ids.add(row.metric_id)
    metrics = {row.code: row for row in (await db.scalars(select(Metric))).all()}
    runs = (
        await db.scalars(
            select(SourceSyncRun)
            .where(
                SourceSyncRun.status.in_(["success", "partial_success"]),
                SourceSyncRun.finished_at.is_not(None),
            )
            .order_by(SourceSyncRun.finished_at)
        )
    ).all()
    last_source = {row.source_name: row.finished_at for row in runs}
    revenue = sum((x.amount for x in orders), D(0))
    cost = sum((x.amount for x in finance), D(0))
    counts = defaultdict(int)
    for row in orders:
        counts[row.customer_id] += 1
    revenue_target = summed[metric_id("revenue")] if metric_id("revenue") in target_ids else None
    alert_stmt = scope(
        select(func.count())
        .select_from(Alert)
        .where(
            Alert.severity == "critical",
            Alert.status.in_(["active", "acknowledged"]),
            Alert.period_end >= start,
            Alert.period_start <= end,
        ),
        Alert,
    )
    values = {
        "revenue": revenue,
        "gross_margin": percentage(revenue - cost, revenue),
        "on_time_orders": percentage(sum(x.completed_at <= x.due_at for x in orders), len(orders)),
        "defect_rate": percentage(
            sum(x.defective_quantity for x in productions), sum(x.actual_quantity for x in productions)
        ),
        "new_customers": D(sum(lo <= first < hi for _, first in firsts)),
        "active_customers": D(len(counts)),
        "repeat_purchase_rate": percentage(sum(n >= 2 for n in counts.values()), len(counts)),
        "support_sla": percentage(sum(x.closed_at <= x.sla_deadline for x in tickets), len(tickets)),
        "capacity_utilization": percentage(
            sum((x.actual_load_hours for x in productions), D(0)),
            sum((x.available_hours for x in capacities), D(0)),
        ),
        "staffing_coverage": percentage(
            sum(x.available_headcount for x in latest.values()),
            sum(x.required_headcount for x in latest.values()),
        ),
        "sales_plan_achievement": percentage(revenue, revenue_target),
        "critical_alerts_count": D(await db.scalar(alert_stmt)),
    }
    now = datetime.now(UTC)
    today = datetime.now(ZoneInfo(get_settings().report_timezone)).date()
    results = []
    for code, name, unit, sources, direction, category, default_target, formula in DEFINITIONS:
        metric = metrics.get(code)
        actual = values[code]
        target = (
            (metric.target_value if metric else default_target)
            if default_target is not None
            else summed[metric_id(code)]
            if metric_id(code) in target_ids
            else None
        )
        missing = [source for source in sources if source != "system" and source not in last_source]
        reason = None
        if missing:
            actual = None
            reason = "SOURCE_NOT_LOADED"
        elif start > today and code != "critical_alerts_count":
            actual = None
            reason = "FUTURE_PERIOD"
        elif code == "gross_margin" and order_ids and not order_ids.issubset({x.order_id for x in finance}):
            actual = None
            reason = "DIRECT_COST_MISSING"
        elif code == "staffing_coverage" and not latest:
            actual = None
            reason = "HR_SNAPSHOT_MISSING"
        status, achievement, deviation = classify(actual, target, direction)
        if status == "no_data" and not reason:
            reason = (
                "TARGET_MISSING"
                if target is None and actual is not None
                else "TARGET_ZERO"
                if target == 0
                else "ZERO_DENOMINATOR"
            )
        ignored = ["product_id"] if code == "staffing_coverage" and product else []
        notices = ["Фильтр продукта не применяется"] if ignored else []
        if code == "staffing_coverage":
            notices.append(
                "Последний кадровый снимок не позже конца периода; начало периода не ограничивает выбор снимка"
            )
        supported = ["department"] + (["product"] if code != "staffing_coverage" else [])
        if code == "revenue":
            supported += ["order", "channel", "campaign"]
        if code in {"defect_rate", "support_sla"}:
            supported += ["cause"]
        if code == "support_sla":
            supported += ["order"]
        forecast = None
        method = None
        if code in {"revenue", "sales_plan_achievement"} and start <= today < end and actual is not None:
            projected = revenue / D((today - start).days + 1) * D((end - start).days + 1)
            forecast = projected if code == "revenue" else percentage(projected, revenue_target)
            method = "calendar_day_run_rate"
        result = {
            "id": metric.id if metric else metric_id(code),
            "code": code,
            "name": metric.name if metric else name,
            "description": metric.description if metric else name,
            "category": category,
            "actual": number(actual, unit),
            "target": number(target, unit),
            "forecast": number(forecast, unit),
            "unit": unit,
            "currency": "BYN" if unit == "BYN" else None,
            "achievement_percent": number(achievement),
            "deviation_percent": number(deviation),
            "status": status,
            "direction": direction,
            "formula": metric.formula if metric else formula,
            "formula_version": "1",
            "source": sources,
            "updated_at": now,
            "source_updated_at": min([last_source[s] for s in sources if s in last_source], default=None),
            "forecast_method": method,
            "reason_code": reason,
            "reason": {
                "SOURCE_NOT_LOADED": "Источник ещё не загружен",
                "FUTURE_PERIOD": "За будущий период нет фактических данных",
                "DIRECT_COST_MISSING": "Не для всех завершённых заказов загружены прямые затраты",
                "HR_SNAPSHOT_MISSING": "Нет кадровых снимков",
                "TARGET_MISSING": "План не задан",
                "TARGET_ZERO": "Относительное отклонение от нулевого плана не определено",
                "ZERO_DENOMINATOR": "Недостаточно данных для расчёта доли",
            }.get(reason),
            "context": {**context, "ignored_filters": ignored},
            "notices": notices,
            "supported_group_by": supported,
        }
        results.append(result)
    return results, context


async def recalculate(db, actor=None, request=None):
    from types import SimpleNamespace

    from app.models import Department, Product

    # Serialize mutations before the underlying write in routes; this lock also protects direct imports.
    await db.execute(text("SELECT pg_advisory_xact_lock(178901234)"))
    now = datetime.now(UTC)
    today = datetime.now(ZoneInfo(get_settings().report_timezone)).date()
    start = today.replace(day=1)
    system_actor = SimpleNamespace(role="admin", department_id=None)
    departments = (await db.scalars(select(Department.id).where(Department.is_active.is_(True)))).all()
    products = (await db.scalars(select(Product.id).where(Product.is_active.is_(True)))).all()
    metric_rows = {row.code: row for row in (await db.scalars(select(Metric))).all()}
    if not metric_rows:
        return {"calculated_at": now, "metric_values_updated": 0, "alerts_created": 0, "alerts_updated": 0}
    contexts = (
        [(None, None)]
        + [(department, None) for department in departments]
        + [(None, product) for product in products]
        + [(department, product) for department in departments for product in products]
    )
    created = 0
    updated = 0
    count = 0
    for department, product in contexts:
        values, _ = await calculate(
            db,
            SimpleNamespace(date_from=start, date_to=today, department_id=department, product_id=product),
            system_actor,
        )
        for value in values:
            code = value["code"]
            if code == "critical_alerts_count" or code not in metric_rows:
                continue
            if code == "staffing_coverage" and product:
                continue
            metric = metric_rows[code]
            snapshot = await db.scalar(
                select(MetricValue).where(
                    MetricValue.metric_id == metric.id,
                    MetricValue.department_id.is_(None)
                    if department is None
                    else MetricValue.department_id == department,
                    MetricValue.product_id.is_(None)
                    if product is None
                    else MetricValue.product_id == product,
                    MetricValue.period_start == start,
                    MetricValue.period_end == today,
                )
            )
            if snapshot is None:
                snapshot = MetricValue(
                    metric_id=metric.id,
                    department_id=department,
                    product_id=product,
                    period_start=start,
                    period_end=today,
                )
                db.add(snapshot)
            snapshot.actual_value = value["actual"]
            snapshot.target_value = value["target"]
            snapshot.forecast_value = value["forecast"]
            snapshot.deviation_percent = value["deviation_percent"]
            snapshot.status = value["status"]
            snapshot.formula_version = "1"
            snapshot.calculated_at = now
            snapshot.source_updated_at = value["source_updated_at"]
            snapshot.reason_code = value["reason_code"]
            count += 1
            await db.flush()
            alert = await db.scalar(
                select(Alert).where(
                    Alert.metric_code == code,
                    Alert.period_start == start,
                    Alert.department_id.is_(None)
                    if department is None
                    else Alert.department_id == department,
                    Alert.product_id.is_(None) if product is None else Alert.product_id == product,
                )
            )
            if alert:
                alert.metric_value_id = snapshot.id
                alert.actual = value["actual"]
                alert.target = value["target"]
                alert.deviation_percent = value["deviation_percent"]
                updated += 1
            elif value["status"] == "critical":
                alert = Alert(
                    metric_value_id=snapshot.id,
                    metric_code=code,
                    department_id=department,
                    product_id=product,
                    period_start=start,
                    period_end=date(today.year, today.month, calendar.monthrange(today.year, today.month)[1]),
                    title="Отклонение: " + value["name"],
                    description="Критическое отклонение от демонстрационного плана",
                    actual=value["actual"],
                    target=value["target"],
                    opening_actual=value["actual"],
                    opening_target=value["target"],
                    deviation_percent=value["deviation_percent"],
                    severity="critical",
                    status="active",
                )
                db.add(alert)
                await db.flush()
                record(
                    db,
                    "alert.created",
                    "alert",
                    actor=actor,
                    object_id=alert.id,
                    object_name=alert.title,
                    new={"status": "active", "actual": value["actual"], "target": value["target"]},
                    request=request,
                )
                created += 1
    record(
        db,
        "metrics.recalculated",
        "metric",
        actor=actor,
        details={"snapshots": count, "alerts_created": created},
        request=request,
    )
    return {
        "calculated_at": now,
        "metric_values_updated": count,
        "alerts_created": created,
        "alerts_updated": updated,
    }
