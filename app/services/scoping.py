"""Shared query-scoping and search-pattern helpers."""

from sqlalchemy import select

from app.models import Order


def like_pattern(value: str) -> str:
    """Escape LIKE/ILIKE wildcards and wrap ``value`` for a substring search."""
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def apply_department(stmt, model, department):
    if department:
        return stmt.where(model.department_id == department)
    return stmt


def apply_product(stmt, model, product_id):
    """Filter by product, falling back to the linked order for order-scoped models."""
    if not product_id:
        return stmt
    if hasattr(model, "product_id"):
        return stmt.where(model.product_id == product_id)
    if hasattr(model, "order_id"):
        return stmt.where(model.order_id.in_(select(Order.id).where(Order.product_id == product_id)))
    return stmt
