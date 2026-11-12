"""Read-only enrichment of already scoped API records for existing screens."""

from sqlalchemy import select

from app.core.permissions import scope_statement
from app.models import CapacityPlan, Decision, Department, Metric, Order, Product, Task


async def alert_labels(db, items):
    if not items:
        return items
    lookups = []
    for model, field, values, label in [
        (Department, Department.id, {item["department_id"] for item in items}, "name"),
        (Product, Product.id, {item["product_id"] for item in items}, "name"),
        (Metric, Metric.code, {item["metric_code"] for item in items}, "name"),
    ]:
        rows = (await db.scalars(select(model).where(field.in_(values - {None})))).all()
        lookups.append({getattr(row, field.key): getattr(row, label) for row in rows})
    departments, products, metrics = lookups
    return [
        {
            **item,
            "department_name": departments.get(item["department_id"]),
            "product_name": products.get(item["product_id"]),
            "metric_name": metrics.get(item["metric_code"], item["metric_code"]),
        }
        for item in items
    ]


async def production_labels(db, items):
    if not items:
        return items
    products = {
        row.id: row.name
        for row in (
            await db.scalars(select(Product).where(Product.id.in_({x["product_id"] for x in items})))
        ).all()
    }
    departments = {
        row.id: row.name
        for row in (
            await db.scalars(select(Department).where(Department.id.in_({x["department_id"] for x in items})))
        ).all()
    }
    plans = (
        await db.scalars(
            select(CapacityPlan).where(
                CapacityPlan.plan_date.in_({x["production_date"] for x in items}),
                CapacityPlan.department_id.in_({x["department_id"] for x in items}),
                CapacityPlan.product_id.in_({x["product_id"] for x in items}),
            )
        )
    ).all()
    capacity = {(p.plan_date, p.department_id, p.product_id): float(p.available_hours) for p in plans}
    return [
        {
            **item,
            "product_name": products.get(item["product_id"]),
            "department_name": departments.get(item["department_id"]),
            "planned_capacity": capacity.get(
                (item["production_date"], item["department_id"], item["product_id"])
            ),
        }
        for item in items
    ]


async def alert_context(db, alert, user):
    # Only explicitly linked workflow records; a common period does not prove a link.
    decisions = (
        await db.scalars(
            scope_statement(select(Decision).where(Decision.alert_id == alert.id), Decision, user)
        )
    ).all()
    tasks = scope_statement(
        select(Task.order_id).where(Task.alert_id == alert.id, Task.deleted_at.is_(None)), Task, user
    )
    orders = (
        await db.scalars(
            scope_statement(select(Order).where(Order.id.in_(tasks)), Order, user)
            .order_by(Order.created_at.desc(), Order.id)
            .limit(20)
        )
    ).all()
    return {
        "causes": [
            {"text": cause, "confirmed": False} for cause in sorted({d.cause for d in decisions if d.cause})
        ],
        "related_orders": [
            {"id": order.id, "label": order.order_number, "amount": float(order.amount)} for order in orders
        ],
    }
