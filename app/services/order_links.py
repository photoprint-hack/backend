"""Shared order/deal checks for API writes and source snapshots."""

from types import SimpleNamespace

from sqlalchemy import select

from app.models import Deal, Order


class OrderDealLinkError(ValueError):
    pass


async def validate_pair(db, order, deal):
    if (
        order.customer_id != deal.customer_id
        or order.department_id != deal.department_id
        or (deal.product_id is not None and order.product_id != deal.product_id)
    ):
        raise OrderDealLinkError("Сделка не соответствует клиенту, подразделению или продукту заказа")
    if (deal.order_id is not None and deal.order_id != order.id) or (
        order.crm_deal_id is not None and order.crm_deal_id != deal.id
    ):
        raise OrderDealLinkError("Заказ или сделка уже связаны с другим объектом")
    if deal.id is not None:
        competing = select(Order.id).where(Order.crm_deal_id == deal.id)
        if order.id is not None:
            competing = competing.where(Order.id != order.id)
        if await db.scalar(competing.limit(1)):
            raise OrderDealLinkError("Сделка уже связана с другим заказом")
    if order.id is not None:
        competing = select(Deal.id).where(Deal.order_id == order.id)
        if deal.id is not None:
            competing = competing.where(Deal.id != deal.id)
        if await db.scalar(competing.limit(1)):
            raise OrderDealLinkError("Заказ уже связан с другой сделкой")


async def validate_import_links(db, model, values, existing):
    """Validate before mutating the stored object, including reverse-only references."""
    if model not in {Order, Deal}:
        return
    candidate = SimpleNamespace(id=existing.id if existing else None, **values)
    if model is Order:
        deals = {}
        if values.get("crm_deal_id"):
            deal = await db.get(Deal, values["crm_deal_id"])
            deals[deal.id] = deal
        if candidate.id:
            for deal in (await db.scalars(select(Deal).where(Deal.order_id == candidate.id))).all():
                deals[deal.id] = deal
        for deal in deals.values():
            await validate_pair(db, candidate, deal)
    else:
        orders = {}
        if values.get("order_id"):
            order = await db.get(Order, values["order_id"])
            orders[order.id] = order
        if candidate.id:
            for order in (await db.scalars(select(Order).where(Order.crm_deal_id == candidate.id))).all():
                orders[order.id] = order
        for order in orders.values():
            await validate_pair(db, order, candidate)
