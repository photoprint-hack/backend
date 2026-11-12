import calendar
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.exceptions import ApiError
from app.core.permissions import WRITE_ROLES, require_role, scope_statement
from app.models import (
    Alert,
    AuditLog,
    Campaign,
    Decision,
    Department,
    Order,
    Product,
    ProductionRecord,
    SupportInteraction,
    Task,
    User,
)
from app.schemas.analytics.alerts import AlertCard, AlertOut, AlertPatch, AlertsQuery
from app.schemas.analytics.dashboard import Dashboard
from app.schemas.analytics.metrics import (
    BreakdownPage,
    BreakdownQuery,
    HistoryQuery,
    Kpi,
    MetricHistoryPage,
    MetricsQuery,
    RecalculateResult,
)
from app.schemas.common import Data, Page, Schema, page
from app.schemas.shared.events import ChangeEvent
from app.schemas.shared.query import BusinessQuery
from app.services import analytics, audit, workflow
from app.services.presentation import alert_context, alert_labels
from app.services.serialization import columns, serialize_many

router = APIRouter(tags=["analytics"])
Q = Annotated[BusinessQuery, Query()]


HQ = Annotated[HistoryQuery, Query()]
BQ = Annotated[BreakdownQuery, Query()]


@router.get("/dashboard", response_model=Data[Dashboard])
async def dashboard(db: DB, user: CurrentUser, query: Q):
    kpis, context = await analytics.calculate(db, query, user)
    recent = {}
    counts = {}
    for model, label in [(Alert, "alerts"), (Decision, "decisions"), (Task, "tasks")]:
        stmt = scope_statement(select(model), model, user, query.department_id)
        if model is Alert:
            stmt = stmt.where(
                Alert.status.in_(["active", "acknowledged"]),
                Alert.period_end >= context["date_from"],
                Alert.period_start <= context["date_to"],
            )
            if query.product_id:
                stmt = stmt.where(Alert.product_id == query.product_id)
        else:
            stmt = stmt.where(model.status.not_in(["completed", "cancelled"]))
            if model is Task:
                stmt = stmt.where(Task.deleted_at.is_(None))
            if query.product_id:
                condition = model.alert_id.in_(select(Alert.id).where(Alert.product_id == query.product_id))
                if model is Task:
                    condition = condition | Task.order_id.in_(
                        select(Order.id).where(Order.product_id == query.product_id)
                    )
                stmt = stmt.where(condition)
        counts[label] = await db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (await db.scalars(stmt.order_by(model.created_at.desc(), model.id).limit(5))).all()
        recent[label] = (
            await alert_labels(db, [alert_out(row, user) for row in rows])
            if model is Alert
            else await serialize_many(db, rows, user)
        )
    tasks_stmt = scope_statement(
        select(func.count())
        .select_from(Task)
        .where(
            Task.deleted_at.is_(None),
            Task.status.in_(["new", "in_progress"]),
            Task.deadline < datetime.now(UTC),
        ),
        Task,
        user,
        query.department_id,
    )
    if query.product_id:
        tasks_stmt = tasks_stmt.where(
            (Task.order_id.in_(select(Order.id).where(Order.product_id == query.product_id)))
            | (Task.alert_id.in_(select(Alert.id).where(Alert.product_id == query.product_id)))
        )
    return {
        "data": {
            "period": {"date_from": context["date_from"], "date_to": context["date_to"]},
            "filters": {"department_id": context["department_id"], "product_id": context["product_id"]},
            "kpis": kpis,
            "active_alerts_count": counts["alerts"],
            "critical_alerts_count": next(x["actual"] for x in kpis if x["code"] == "critical_alerts_count"),
            "active_decisions_count": counts["decisions"],
            "active_tasks_count": counts["tasks"],
            "overdue_tasks_count": await db.scalar(tasks_stmt),
            "recent_alerts": recent["alerts"],
            "recent_decisions": recent["decisions"],
            "recent_tasks": recent["tasks"],
            "updated_at": datetime.now(UTC),
        }
    }


@router.get("/metrics", response_model=Page[Kpi])
async def metrics(db: DB, user: CurrentUser, query: Annotated[MetricsQuery, Query()]):
    values, _ = await analytics.calculate(db, query, user)
    if query.category:
        values = [x for x in values if x["category"] == query.category]
    if query.status:
        values = [x for x in values if x["status"] == query.status]
    values.sort(key=lambda x: x[query.sort_by], reverse=query.sort_order == "desc")
    return page(
        values[(query.page - 1) * query.page_size : query.page * query.page_size],
        len(values),
        query.page,
        query.page_size,
    )


class Recalculate(Schema):
    date_from: date | None = None
    date_to: date | None = None


@router.post("/metrics/recalculate", response_model=Data[RecalculateResult])
async def recalculate(payload: Recalculate, request: Request, db: DB, user: CurrentUser):
    require_role(user, {"admin"})
    today = datetime.now(analytics.ZoneInfo(analytics.get_settings().report_timezone)).date()
    if (payload.date_from and payload.date_from != today.replace(day=1)) or (
        payload.date_to and payload.date_to != today
    ):
        raise ApiError(422, "VALIDATION_ERROR", "Сохранённый пересчёт использует текущий месяц по сегодня")
    result = await analytics.recalculate(db, user, request)
    await db.commit()
    return {"data": result}


@router.get("/metrics/{code}", response_model=Data[Kpi])
async def metric(code: str, db: DB, user: CurrentUser, query: Q):
    values, _ = await analytics.calculate(db, query, user)
    found = next((x for x in values if x["code"] == code), None)
    if not found:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Показатель не найден")
    return {"data": found}


@router.get("/metrics/{code}/history", response_model=MetricHistoryPage)
async def history(code: str, db: DB, user: CurrentUser, query: HQ):
    interval = query.interval
    start, end, _, _ = analytics.period(query)
    if code not in {x[0] for x in analytics.DEFINITIONS}:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Показатель не найден")
    if interval == "day" and (end - start).days + 1 > 31:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Дневная детализация доступна максимум за 31 день; используйте interval=week",
        )
    # Demo-scale tradeoff: each period bucket re-runs the full KPI calculation.
    periods = []
    cursor = start
    while cursor <= end:
        if interval == "day":
            stop = cursor
        elif interval == "week":
            stop = min(end, cursor + timedelta(days=6 - cursor.weekday()))
        else:
            stop = min(end, cursor.replace(day=calendar.monthrange(cursor.year, cursor.month)[1]))
        periods.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    items = []
    for left, right in periods[(query.page - 1) * query.page_size : query.page * query.page_size]:
        part = query.model_copy(update={"date_from": left, "date_to": right})
        values, _ = await analytics.calculate(db, part, user)
        value = next(x for x in values if x["code"] == code)
        if code == "critical_alerts_count":
            zone = analytics.ZoneInfo(analytics.get_settings().report_timezone)
            cutoff = datetime.combine(right + timedelta(days=1), datetime.min.time(), zone)
            stmt = scope_statement(
                select(Alert).where(Alert.created_at < cutoff), Alert, user, query.department_id
            )
            if query.product_id:
                stmt = stmt.where(Alert.product_id == query.product_id)
            alerts = (await db.scalars(stmt)).all()
            count = 0
            for item in alerts:
                last = await db.scalar(
                    select(AuditLog)
                    .where(
                        AuditLog.object_type == "alert",
                        AuditLog.object_id == item.id,
                        AuditLog.created_at < cutoff,
                    )
                    .order_by(AuditLog.created_at.desc())
                    .limit(1)
                )
                status = (last.new_values or {}).get("status", "active") if last else "active"
                if status in {"active", "acknowledged"}:
                    count += 1
            value["actual"] = count
        items.append(
            {
                "period_start": left,
                "period_end": right,
                "actual": value["actual"],
                "target": value["target"],
                "forecast": value["forecast"],
                "status": value["status"],
                "updated_at": value["updated_at"],
            }
        )
    return {**page(items, len(periods), query.page, query.page_size), "metric_code": code}


@router.get("/metrics/{code}/breakdown", response_model=BreakdownPage)
async def breakdown(code: str, db: DB, user: CurrentUser, query: BQ):
    group_by = query.group_by
    values, context = await analytics.calculate(db, query, user)
    kpi = next((x for x in values if x["code"] == code), None)
    if not kpi:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Показатель не найден")
    if group_by not in kpi["supported_group_by"]:
        raise ApiError(422, "UNSUPPORTED_GROUP_BY", "Этот разрез недоступен для показателя")
    start, end, lo, hi = analytics.period(query)
    grouped = defaultdict(list)
    if group_by in {"department", "product"}:
        # Demo-scale tradeoff: KPI values are recalculated per breakdown group.
        model = Department if group_by == "department" else Product
        stmt = select(model)
        if group_by == "department" and context["department_id"]:
            stmt = stmt.where(Department.id == context["department_id"])
        if group_by == "product" and query.product_id:
            stmt = stmt.where(Product.id == query.product_id)
        labels = (await db.scalars(stmt)).all()
        total = len(labels)
        items = []
        for label in labels[(query.page - 1) * query.page_size : query.page * query.page_size]:
            sub = query.model_copy(update={group_by + "_id": label.id})
            sub_values, _ = await analytics.calculate(db, sub, user)
            value = next(x for x in sub_values if x["code"] == code)
            items.append(
                {
                    "key": str(label.id),
                    "name": label.name,
                    "actual": value["actual"],
                    "target": value["target"],
                    "deviation_percent": value["deviation_percent"],
                    "source_records_count": 0,
                    "cause": None,
                    "cause_status": "requires_review",
                    "links": [],
                }
            )
    else:
        model = (
            Order if code == "revenue" else ProductionRecord if code == "defect_rate" else SupportInteraction
        )
        stmt = scope_statement(select(model), model, user, query.department_id)
        if model is Order:
            stmt = stmt.where(Order.status == "completed", Order.completed_at >= lo, Order.completed_at < hi)
        elif model is ProductionRecord:
            stmt = stmt.where(
                ProductionRecord.production_date >= start, ProductionRecord.production_date <= end
            )
        else:
            stmt = stmt.where(
                SupportInteraction.closed_at >= lo,
                SupportInteraction.closed_at < hi,
                SupportInteraction.status == "closed",
                SupportInteraction.sla_deadline.is_not(None),
            )
        if query.product_id:
            stmt = (
                stmt.where(model.product_id == query.product_id)
                if hasattr(model, "product_id")
                else stmt.where(
                    model.order_id.in_(select(Order.id).where(Order.product_id == query.product_id))
                )
            )
        for row in (await db.scalars(stmt)).all():
            key = (
                str(row.id)
                if group_by == "order" and model is Order
                else str(row.order_id)
                if group_by == "order"
                else getattr(row, "cause", None)
                if group_by == "cause"
                else getattr(row, group_by if group_by == "channel" else "campaign_id", None)
            )
            grouped[key].append(row)
        keys = sorted(grouped, key=lambda x: str(x))
        total = len(keys)
        items = []
        for key in keys[(query.page - 1) * query.page_size : query.page * query.page_size]:
            rows = grouped[key]
            actual = (
                sum((x.amount for x in rows), analytics.D(0))
                if code == "revenue"
                else analytics.percentage(
                    sum(x.defective_quantity for x in rows), sum(x.actual_quantity for x in rows)
                )
                if code == "defect_rate"
                else analytics.percentage(sum(x.closed_at <= x.sla_deadline for x in rows), len(rows))
            )
            label = (
                rows[0].order_number
                if group_by == "order" and model is Order
                else str(key)
                if key
                else "Не указано"
            )
            if group_by == "campaign" and key:
                campaign = await db.get(Campaign, UUID(key))
                label = campaign.name if campaign else "Не указано"
            links = [
                {
                    "object_type": "order"
                    if model is Order
                    else "production_record"
                    if model is ProductionRecord
                    else "support_interaction",
                    "object_id": r.id,
                    "label": getattr(r, "order_number", str(r.id)),
                }
                for r in rows[:20]
            ]
            items.append(
                {
                    "key": str(key or "unknown"),
                    "name": label,
                    "actual": analytics.number(actual, kpi["unit"]),
                    "target": None,
                    "deviation_percent": None,
                    "source_records_count": len(rows),
                    "cause": key if group_by == "cause" else None,
                    "cause_status": "known" if group_by == "cause" and key else "requires_review",
                    "links": links,
                }
            )
    return {
        **page(items, total, query.page, query.page_size),
        "metric_code": code,
        "group_by": group_by,
        "context": context,
    }


def alert_out(row, user):
    item = columns(row)
    item["allowed_actions"] = ["read"] + (
        ["acknowledge", "resolve"] if user.role in WRITE_ROLES and row.status != "resolved" else []
    )
    return item


@router.get("/alerts", response_model=Page[AlertOut])
async def alerts(db: DB, user: CurrentUser, query: Annotated[AlertsQuery, Query()]):
    require_role(user, {"admin", "director", "manager", "analyst"})
    rows, total = await workflow.list_objects(db, Alert, query, user)
    return page(
        await alert_labels(db, [alert_out(x, user) for x in rows]), total, query.page, query.page_size
    )


@router.get("/alerts/{identifier}", response_model=Data[AlertCard])
async def get_alert(identifier: UUID, db: DB, user: CurrentUser):
    require_role(user, {"admin", "director", "manager", "analyst"})
    obj = await workflow.scoped(db, Alert, identifier, user)
    q = BusinessQuery(
        department_id=obj.department_id,
        product_id=obj.product_id,
        date_from=obj.period_start,
        date_to=min(
            obj.period_end, datetime.now(analytics.ZoneInfo(analytics.get_settings().report_timezone)).date()
        ),
    )
    values, _ = await analytics.calculate(db, q, user)
    links = {}
    for model, name in [(Decision, "decisions"), (Task, "tasks")]:
        stmt = scope_statement(select(model).where(model.alert_id == obj.id), model, user)
        if model is Task:
            stmt = stmt.where(Task.deleted_at.is_(None))
        rows = (await db.scalars(stmt.order_by(model.created_at.desc()).limit(20))).all()
        links[name] = [{"id": x.id, "name": x.title} for x in rows]
    return {
        "data": {
            "alert": (await alert_labels(db, [alert_out(obj, user)]))[0],
            **(await alert_context(db, obj, user)),
            "metric": next(x for x in values if x["code"] == obj.metric_code),
            **links,
            "decisions_url": f"/api/v1/decisions?alert_id={obj.id}",
            "tasks_url": f"/api/v1/tasks?alert_id={obj.id}",
            "breakdown_url": f"/api/v1/metrics/{obj.metric_code}/breakdown",
        }
    }


@router.patch("/alerts/{identifier}", response_model=Data[AlertOut])
async def patch_alert(identifier: UUID, payload: AlertPatch, request: Request, db: DB, user: CurrentUser):
    require_role(user, WRITE_ROLES)
    obj = await workflow.scoped(db, Alert, identifier, user, lock=True)
    workflow.transition(
        obj.status, payload.status, {"active": {"acknowledged", "resolved"}, "acknowledged": {"resolved"}}
    )
    if obj.status == "active" and payload.status == "resolved" and not payload.comment:
        raise ApiError(422, "VALIDATION_ERROR", "Для прямого закрытия нужен комментарий")
    old = {"status": obj.status}
    obj.status = payload.status
    obj.updated_at = datetime.now(UTC)
    audit.record(
        db,
        "alert.updated",
        "alert",
        actor=user,
        object_id=obj.id,
        object_name=obj.title,
        old=old,
        new={"status": obj.status},
        details={"comment": payload.comment},
        request=request,
    )
    await db.commit()
    return {"data": (await alert_labels(db, [alert_out(obj, user)]))[0]}


@router.get("/alerts/{identifier}/history", response_model=Page[ChangeEvent])
async def alert_history(
    identifier: UUID,
    db: DB,
    user: CurrentUser,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    require_role(user, {"admin", "director", "manager", "analyst"})
    await workflow.scoped(db, Alert, identifier, user)
    stmt = select(AuditLog).where(
        AuditLog.object_type == "alert", AuditLog.object_id == identifier, AuditLog.status == "success"
    )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.scalars(
            stmt.order_by(AuditLog.created_at.desc(), AuditLog.id)
            .offset((page_number - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    actors = {
        x.id: x
        for x in (
            await db.scalars(select(User).where(User.id.in_([x.user_id for x in rows if x.user_id])))
        ).all()
    }
    return page(
        [
            {
                "id": x.id,
                "object_type": "alert",
                "object_id": identifier,
                "action": x.action,
                "changed_by": {"id": x.user_id, "full_name": actors[x.user_id].full_name}
                if x.user_id in actors
                else None,
                "old_values": x.old_values or {},
                "new_values": x.new_values or {},
                "comment": (x.details or {}).get("comment"),
                "created_at": x.created_at,
            }
            for x in rows
        ],
        total,
        page_number,
        page_size,
    )
