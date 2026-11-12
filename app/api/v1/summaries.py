from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.permissions import READ_ROLES, department_scope, require_role
from app.models import (
    CapacityPlan,
    Customer,
    Deal,
    DealEvent,
    FinanceRecord,
    HRSnapshot,
    Order,
    ProductionRecord,
    SourceSyncRun,
)
from app.schemas.catalog.sales import DealOut, DealsQuery, Funnel, SalesSummary
from app.schemas.common import Data, Page, page
from app.schemas.reporting.finance import FinanceSummary
from app.schemas.reporting.hr import HRSummary
from app.schemas.reporting.production import ProductionSummary, QueueQuery
from app.schemas.shared.query import BusinessQuery
from app.schemas.workflow.orders import OrderOut
from app.services.analytics import D, calculate, number, percentage, period
from app.services.scoping import apply_department, apply_product, like_pattern
from app.services.serialization import columns

router = APIRouter(tags=["business-summaries"])
Q = Annotated[BusinessQuery, Query()]


async def loaded(db, source):
    return await db.scalar(
        select(SourceSyncRun.finished_at)
        .where(SourceSyncRun.source_name == source, SourceSyncRun.status.in_(["success", "partial_success"]))
        .order_by(SourceSyncRun.finished_at.desc())
        .limit(1)
    )


def filtered(stmt, model, department, product=None):
    return apply_product(apply_department(stmt, model, department), model, product)


@router.get("/sales/summary", response_model=Data[SalesSummary])
async def sales_summary(db: DB, user: CurrentUser, query: Q):
    values, context = await calculate(db, query, user)
    kpi = {x["code"]: x for x in values}
    _, _, lo, hi = period(query)
    rows = (
        await db.scalars(
            filtered(
                select(Order).where(
                    Order.status == "completed", Order.completed_at >= lo, Order.completed_at < hi
                ),
                Order,
                context["department_id"],
                query.product_id,
            )
        )
    ).all()
    customers = {
        x.id: x
        for x in (
            await db.scalars(select(Customer).where(Customer.id.in_({o.customer_id for o in rows})))
        ).all()
    }
    channels = defaultdict(list)
    segments = defaultdict(list)
    for order in rows:
        channels[order.channel].append(order)
        segments[customers[order.customer_id].segment].append(order)

    def slices(group):
        return [
            {
                "code": code,
                "name": code,
                "orders_count": len(items),
                "revenue": number(sum((r.amount for r in items), D(0)), "BYN"),
                "active_customers": len({r.customer_id for r in items}),
            }
            for code, items in sorted(group.items())
        ]

    deals = (
        await db.scalars(
            filtered(
                select(Deal).where(Deal.created_at >= lo, Deal.created_at < hi),
                Deal,
                context["department_id"],
                query.product_id,
            )
        )
    ).all()
    source_ready = await loaded(db, "crm") and await loaded(db, "erp")
    return {
        "data": {
            "context": context,
            "revenue": kpi["revenue"]["actual"],
            "orders_count": len(rows) if source_ready else None,
            "average_check": number(percentage(sum((r.amount for r in rows), D(0)), len(rows)) / 100, "BYN")
            if rows and source_ready
            else None,
            "new_customers": kpi["new_customers"]["actual"],
            "active_customers": kpi["active_customers"]["actual"],
            "repeat_purchase_rate": kpi["repeat_purchase_rate"]["actual"],
            "sales_plan_achievement": kpi["sales_plan_achievement"]["actual"],
            "conversion_percent": number(percentage(sum(r.stage == "won" for r in deals), len(deals)))
            if source_ready
            else None,
            "currency": "BYN",
            "channels": slices(channels),
            "segments": slices(segments),
            "updated_at": datetime.now(UTC),
        }
    }


@router.get("/sales/funnel", response_model=Data[Funnel])
async def funnel(db: DB, user: CurrentUser, query: Q):
    require_role(user, READ_ROLES)
    department = department_scope(user, query.department_id)
    start, end, lo, hi = period(query)
    rows = (
        await db.scalars(
            filtered(
                select(Deal).where(Deal.created_at >= lo, Deal.created_at < hi),
                Deal,
                department,
                query.product_id,
            )
        )
    ).all()
    counts = {stage: set() for stage in ["new", "qualified", "proposal", "won", "lost"]}
    for row in rows:
        counts["new"].add(row.id)
    for event in (
        await db.scalars(select(DealEvent).where(DealEvent.deal_id.in_([x.id for x in rows])))
    ).all():
        if event.new_stage in counts:
            counts[event.new_stage].add(event.deal_id)
    stages = []
    previous = len(rows)
    for stage in counts:
        count = len(counts[stage])
        denominator = len(rows) if stage in {"new", "lost"} else previous
        stages.append(
            {
                "code": stage,
                "name": {
                    "new": "Новая",
                    "qualified": "Квалифицирована",
                    "proposal": "Предложение",
                    "won": "Выиграна",
                    "lost": "Потеряна",
                }[stage],
                "count": count,
                "conversion_from_previous_percent": number(percentage(count, denominator)),
            }
        )
        if stage != "lost":
            previous = count
    return {
        "data": {
            "context": {
                "date_from": start,
                "date_to": end,
                "department_id": department,
                "product_id": query.product_id,
            },
            "cohort_count": len(rows),
            "stages": stages,
            "conversion_percent": number(percentage(sum(row.stage == "won" for row in rows), len(rows))),
            "updated_at": await loaded(db, "crm"),
        }
    }


@router.get("/sales/deals", response_model=Page[DealOut])
async def deals(db: DB, user: CurrentUser, query: Annotated[DealsQuery, Query()]):
    require_role(user, READ_ROLES)
    department = department_scope(user, query.department_id)
    _, _, lo, hi = period(query)
    stmt = filtered(
        select(Deal).where(Deal.created_at >= lo, Deal.created_at < hi), Deal, department, query.product_id
    )
    for key in ["stage", "channel", "campaign_id"]:
        value = getattr(query, key)
        if value is not None:
            stmt = stmt.where(getattr(Deal, key) == value)
    if query.search:
        stmt = stmt.where(
            Deal.customer_id.in_(
                select(Customer.id).where(Customer.name.ilike(like_pattern(query.search), escape="\\"))
            )
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.scalars(
            stmt.order_by(Deal.created_at.desc(), Deal.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    customers = {
        x.id: x.name
        for x in (
            await db.scalars(select(Customer).where(Customer.id.in_({x.customer_id for x in rows})))
        ).all()
    }
    return page(
        [{**columns(x), "customer_name": customers[x.customer_id]} for x in rows],
        total,
        query.page,
        query.page_size,
    )


@router.get("/production/summary", response_model=Data[ProductionSummary])
async def production(db: DB, user: CurrentUser, query: Q):
    require_role(user, READ_ROLES)
    department = department_scope(user, query.department_id)
    start, end, _, _ = period(query)
    rows = (
        await db.scalars(
            filtered(
                select(ProductionRecord).where(
                    ProductionRecord.production_date >= start, ProductionRecord.production_date <= end
                ),
                ProductionRecord,
                department,
                query.product_id,
            )
        )
    ).all()
    capacity = await db.scalar(
        filtered(
            select(func.sum(CapacityPlan.available_hours)).where(
                CapacityPlan.plan_date >= start, CapacityPlan.plan_date <= end
            ),
            CapacityPlan,
            department,
            query.product_id,
        )
    )
    queue = await db.scalar(
        filtered(
            select(func.sum(Order.quantity)).where(
                Order.status.in_(["new", "in_progress"]),
                Order.production_status.in_(["queued", "in_progress"]),
            ),
            Order,
            department,
            query.product_id,
        )
    )
    ready = await loaded(db, "erp")
    planned = sum(x.planned_quantity for x in rows)
    actual = sum(x.actual_quantity for x in rows)
    hours = sum((x.actual_load_hours for x in rows), D(0))
    defects = sum(x.defective_quantity for x in rows)
    values = {
        "planned_quantity": planned,
        "actual_quantity": actual,
        "plan_achievement_percent": number(percentage(actual, planned)),
        "queue_quantity": queue or 0,
        "average_lead_time_hours": number(sum((x.lead_time_hours for x in rows), D(0)) / len(rows))
        if rows
        else None,
        "actual_load_hours": hours,
        "available_capacity_hours": capacity,
        "capacity_utilization_percent": number(percentage(hours, capacity)),
        "downtime_minutes": sum(x.downtime_minutes for x in rows),
        "defective_quantity": defects,
        "reprint_quantity": sum(x.reprint_quantity for x in rows),
        "defect_rate_percent": number(percentage(defects, actual)),
    }
    if not ready:
        values = dict.fromkeys(values)
    return {
        "data": {
            "context": {
                "date_from": start,
                "date_to": end,
                "department_id": department,
                "product_id": query.product_id,
                "ignored_filters": [],
            },
            **values,
            "updated_at": ready,
            "status": "ready" if ready else "no_data",
            "reason": None if ready else "Источник ERP ещё не загружен",
        }
    }


@router.get("/production/queue", response_model=Page[OrderOut])
async def production_queue(db: DB, user: CurrentUser, query: Annotated[QueueQuery, Query()]):
    from app.services.serialization import serialize_many

    require_role(user, READ_ROLES)
    department = department_scope(user, query.department_id)
    stmt = filtered(
        select(Order).where(
            Order.status.in_(["new", "in_progress"]), Order.production_status.in_(["queued", "in_progress"])
        ),
        Order,
        department,
        query.product_id,
    )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.scalars(
            stmt.order_by(Order.due_at, Order.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    return page(await serialize_many(db, rows, user), total, query.page, query.page_size)


@router.get("/finance/summary", response_model=Data[FinanceSummary])
async def finance(db: DB, user: CurrentUser, query: Q):
    kpis, context = await calculate(db, query, user)
    kpis = {x["code"]: x for x in kpis}
    start, end, _, _ = period(query)
    # General costs and budgets are not silently allocated to individual products.
    rows = (
        await db.scalars(
            filtered(
                select(FinanceRecord).where(
                    FinanceRecord.record_date >= start, FinanceRecord.record_date <= end
                ),
                FinanceRecord,
                context["department_id"],
            )
        )
    ).all()
    sums = defaultdict(lambda: D(0))
    for row in rows:
        sums[row.record_type] += row.amount
    ready = await loaded(db, "finance")

    def pf(plan, fact):
        return {
            "plan": number(plan, "BYN") if ready else None,
            "fact": number(fact, "BYN") if ready else None,
            "deviation": number(fact - plan, "BYN") if ready else None,
            "achievement_percent": number(percentage(fact, plan)) if ready else None,
        }

    bdr = {
        kind: pf(sums["budget_" + kind], sums[kind]) for kind in ["revenue", "direct_cost", "operating_cost"]
    }
    bdr["profit"] = pf(
        sums["budget_revenue"] - sums["budget_direct_cost"] - sums["budget_operating_cost"],
        sums["revenue"] - sums["direct_cost"] - sums["operating_cost"],
    )
    bdds = {
        "inflow": pf(sums["budget_cash_inflow"], sums["cash_inflow"]),
        "outflow": pf(sums["budget_cash_outflow"], sums["cash_outflow"]),
        "net": pf(
            sums["budget_cash_inflow"] - sums["budget_cash_outflow"],
            sums["cash_inflow"] - sums["cash_outflow"],
        ),
    }
    margin = kpis["gross_margin"]["actual"]
    revenue = kpis["revenue"]["actual"]
    _, _, revenue_lo, revenue_hi = period(query)
    revenue_orders = filtered(
        select(Order.id).where(
            Order.status == "completed", Order.completed_at >= revenue_lo, Order.completed_at < revenue_hi
        ),
        Order,
        context["department_id"],
        query.product_id,
    )
    raw_cost = await db.scalar(
        select(func.sum(FinanceRecord.amount)).where(
            FinanceRecord.record_type == "direct_cost", FinanceRecord.order_id.in_(revenue_orders)
        )
    )
    direct_cost = (raw_cost or D(0)) if margin is not None else None
    broad = {**context, "product_id": None, "ignored_filters": ["product_id"] if query.product_id else []}
    return {
        "data": {
            "context": context,
            "currency": "BYN",
            "revenue": revenue,
            "direct_cost": number(direct_cost, "BYN"),
            "operating_cost": number(sums["operating_cost"], "BYN") if ready else None,
            "gross_profit": number(D(str(revenue)) - direct_cost, "BYN") if direct_cost is not None else None,
            "gross_margin_percent": margin,
            "bdr": bdr,
            "bdds": bdds,
            "bdr_context": broad,
            "bdds_context": broad,
            "notices": ["Фильтр продукта не применяется к общим расходам и бюджетным сводкам"]
            if query.product_id
            else [],
            "updated_at": ready,
        }
    }


@router.get("/hr/summary", response_model=Data[HRSummary])
async def hr(db: DB, user: CurrentUser, query: Q):
    require_role(user, READ_ROLES)
    department = department_scope(user, query.department_id)
    start, end, _, _ = period(query)
    rows = (
        await db.scalars(
            filtered(
                select(HRSnapshot).where(HRSnapshot.snapshot_date <= end), HRSnapshot, department
            ).order_by(HRSnapshot.snapshot_date)
        )
    ).all()
    latest = {row.department_id: row for row in rows}
    ready = await loaded(db, "hr")
    fields = [
        "planned_headcount",
        "actual_headcount",
        "available_headcount",
        "required_headcount",
        "vacancies_count",
        "absences_count",
    ]
    totals = {
        name: sum(getattr(row, name) for row in latest.values()) if latest and ready else None
        for name in fields
    }
    return {
        "data": {
            "context": {
                "date_from": start,
                "date_to": end,
                "department_id": department,
                "product_id": query.product_id,
                "ignored_filters": ["product_id"] if query.product_id else [],
            },
            **totals,
            "staffing_coverage_percent": number(
                percentage(totals["available_headcount"], totals["required_headcount"])
            )
            if totals["available_headcount"] is not None
            else None,
            "snapshot_dates": sorted({row.snapshot_date for row in latest.values()}),
            "notices": ["Последний снимок не позже конца периода; дата начала не применяется"]
            + (["Фильтр продукта не применяется"] if query.product_id else []),
            "updated_at": ready,
            "status": "ready" if latest and ready else "no_data",
            "reason": None if latest and ready else "Кадровые снимки недоступны",
        }
    }
