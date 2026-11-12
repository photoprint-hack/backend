from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import exists, func, or_, select

from app.api.deps import DB, CurrentUser
from app.core.exceptions import ApiError
from app.core.permissions import READ_ROLES, department_scope, require_role
from app.models import Campaign, Customer, Deal, Order, Product, ProductionRecord, SupportInteraction
from app.schemas.catalog.campaigns import CampaignOut, CampaignsQuery
from app.schemas.catalog.customers import CustomerCard, CustomerOut, CustomersQuery
from app.schemas.catalog.products import ProductOut, ProductsQuery
from app.schemas.common import Data, Page, page
from app.schemas.reporting.production import ProductionOut, ProductionQuery
from app.schemas.reporting.support import SupportOut, SupportQuery
from app.schemas.shared.query import BusinessQuery
from app.services.serialization import columns

router = APIRouter(tags=["catalog"])
Q = Annotated[BusinessQuery, Query()]


def customer_scope(stmt, user, scope=None):
    department = department_scope(user, scope)
    if department:
        stmt = stmt.where(
            or_(
                exists(
                    select(Order.id).where(
                        Order.customer_id == Customer.id, Order.department_id == department
                    )
                ),
                exists(
                    select(Deal.id).where(Deal.customer_id == Customer.id, Deal.department_id == department)
                ),
            )
        )
    return stmt


async def list_catalog(model, db, user, query):
    require_role(user, READ_ROLES)
    department = department_scope(user, getattr(query, "department_id", None))
    stmt = select(model)
    if model is Customer:
        stmt = customer_scope(stmt, user, department)
        if query.segment:
            stmt = stmt.where(Customer.segment == query.segment)
        if query.customer_type:
            stmt = stmt.where(Customer.customer_type == query.customer_type)
    if model in {Deal, ProductionRecord, SupportInteraction} and department:
        stmt = stmt.where(model.department_id == department)
    for field in ("is_active", "category", "channel", "order_id", "product_id", "status"):
        value = getattr(query, field, None)
        if value is not None and hasattr(model, field):
            stmt = stmt.where(getattr(model, field) == value)
    if model is SupportInteraction and getattr(query, "product_id", None):
        stmt = stmt.where(
            SupportInteraction.order_id.in_(select(Order.id).where(Order.product_id == query.product_id))
        )
    if model is Campaign and department:
        own = or_(
            Campaign.id.in_(
                select(Deal.campaign_id).where(
                    Deal.department_id == department, Deal.campaign_id.is_not(None)
                )
            ),
            Campaign.id.in_(
                select(Order.campaign_id).where(
                    Order.department_id == department, Order.campaign_id.is_not(None)
                )
            ),
        )
        stmt = stmt.where(own)
    if query.search:
        field = (
            model.name
            if hasattr(model, "name")
            else model.topic
            if model is SupportInteraction
            else model.external_id
        )
        pattern = "%" + query.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(field.ilike(pattern, escape="\\"))
    if getattr(query, "date_from", None) or getattr(query, "date_to", None):
        from datetime import datetime, time, timedelta
        from zoneinfo import ZoneInfo

        from app.core.config import get_settings

        zone = ZoneInfo(get_settings().report_timezone)
        scoped_first = (
            select(func.min(Order.completed_at))
            .where(Order.customer_id == Customer.id, Order.status == "completed")
            .correlate(Customer)
        )
        if department:
            scoped_first = scoped_first.where(Order.department_id == department)
        field = (
            scoped_first.scalar_subquery()
            if model is Customer
            else model.production_date
            if model is ProductionRecord
            else model.started_at
            if model is Campaign
            else model.created_at
        )
        if model is ProductionRecord:
            if query.date_from:
                stmt = stmt.where(field >= query.date_from)
            if query.date_to:
                stmt = stmt.where(field <= query.date_to)
        else:
            if query.date_from:
                stmt = stmt.where(field >= datetime.combine(query.date_from, time.min, zone))
            if query.date_to:
                stmt = stmt.where(field < datetime.combine(query.date_to + timedelta(days=1), time.min, zone))
    if query.sort_by not in {"created_at", "updated_at", "name", "code", "production_date"} or not hasattr(
        model, query.sort_by
    ):
        raise ApiError(422, "VALIDATION_ERROR", "Недопустимая сортировка")
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    col = getattr(model, query.sort_by)
    rows = (
        await db.scalars(
            stmt.order_by(col.desc() if query.sort_order == "desc" else col.asc(), model.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    items = [columns(row) for row in rows]
    if model is Campaign and user.role == "manager":
        for item in items:
            item["budget"] = None
    if model is Customer and department:
        firsts = dict(
            (
                await db.execute(
                    select(Order.customer_id, func.min(Order.completed_at))
                    .where(
                        Order.department_id == department,
                        Order.status == "completed",
                        Order.customer_id.in_([r.id for r in rows]),
                    )
                    .group_by(Order.customer_id)
                )
            ).all()
        )
        for item in items:
            item["first_order_at"] = firsts.get(item["id"])
    if model is SupportInteraction:
        for item in items:
            item["resolved_within_sla"] = (
                item["closed_at"] <= item["sla_deadline"]
                if item["closed_at"] and item["sla_deadline"]
                else None
            )
    if model is ProductionRecord:
        for item in items:
            item["source_system"] = "erp"
    return page(items, total, query.page, query.page_size)


@router.get("/products", response_model=Page[ProductOut])
async def products(db: DB, user: CurrentUser, query: Annotated[ProductsQuery, Query()]):
    return await list_catalog(Product, db, user, query)


@router.get("/products/{identifier}", response_model=Data[ProductOut])
async def product(identifier: UUID, db: DB, user: CurrentUser):
    require_role(user, READ_ROLES)
    row = await db.get(Product, identifier)
    if not row:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Продукт не найден")
    return {"data": columns(row)}


@router.get("/customers", response_model=Page[CustomerOut])
async def customers(db: DB, user: CurrentUser, query: Annotated[CustomersQuery, Query()]):
    return await list_catalog(Customer, db, user, query)


@router.get("/customers/{identifier}", response_model=Data[CustomerCard])
async def customer(identifier: UUID, db: DB, user: CurrentUser):
    require_role(user, READ_ROLES)
    row = await db.scalar(customer_scope(select(Customer).where(Customer.id == identifier), user))
    if not row:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Клиент не найден")
    item = columns(row)
    if user.role == "manager":
        item["first_order_at"] = await db.scalar(
            select(func.min(Order.completed_at)).where(
                Order.customer_id == identifier,
                Order.department_id == user.department_id,
                Order.status == "completed",
            )
        )
    return {"data": {"customer": item, "orders_url": f"/api/v1/orders?customer_id={identifier}"}}


@router.get("/campaigns", response_model=Page[CampaignOut])
async def campaigns(db: DB, user: CurrentUser, query: Annotated[CampaignsQuery, Query()]):
    return await list_catalog(Campaign, db, user, query)


@router.get("/production/records", response_model=Page[ProductionOut])
async def production_records(db: DB, user: CurrentUser, query: Annotated[ProductionQuery, Query()]):
    return await list_catalog(ProductionRecord, db, user, query)


@router.get("/support/interactions", response_model=Page[SupportOut])
async def interactions(db: DB, user: CurrentUser, query: Annotated[SupportQuery, Query()]):
    return await list_catalog(SupportInteraction, db, user, query)


@router.get("/support/interactions/{identifier}", response_model=Data[SupportOut])
async def interaction(identifier: UUID, db: DB, user: CurrentUser):
    from app.services.workflow import scoped

    require_role(user, READ_ROLES)
    row = await scoped(db, SupportInteraction, identifier, user)
    item = columns(row)
    item["resolved_within_sla"] = (
        row.closed_at <= row.sla_deadline if row.closed_at and row.sla_deadline else None
    )
    return {"data": item}
