from uuid import uuid4

from sqlalchemy import select

from app.models import Order, SupportInteraction
from app.services.scoping import apply_department, apply_product, like_pattern


def test_like_pattern_escapes_wildcards():
    assert like_pattern("50%_x\\y") == "%50\\%\\_x\\\\y%"


def test_apply_product_uses_direct_column_when_available():
    product = uuid4()
    stmt = apply_product(select(Order), Order, product)
    assert str(stmt) == str(select(Order).where(Order.product_id == product))


def test_apply_product_falls_back_to_linked_order():
    product = uuid4()
    stmt = apply_product(select(SupportInteraction), SupportInteraction, product)
    expected = select(SupportInteraction).where(
        SupportInteraction.order_id.in_(select(Order.id).where(Order.product_id == product))
    )
    assert str(stmt) == str(expected)


def test_apply_department_is_a_noop_without_scope():
    stmt = select(Order)
    assert apply_department(stmt, Order, None) is stmt
