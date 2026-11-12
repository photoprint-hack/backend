from datetime import timedelta

from app.models import (
    SupportInteraction,
)
from app.seed.context import SeedContext


async def seed_support(ctx: SeedContext):
    orders = ctx.orders
    add = ctx.add
    for n in range(300):
        uid, dept, product, customer, created, completed, status, amount, quantity = orders[n]
        opened = created + timedelta(hours=1)
        closed = opened + timedelta(hours=8 if n % 5 else 30)
        add(
            SupportInteraction,
            f"support:{n}",
            external_id=f"SUP-{n}",
            customer_id=customer,
            order_id=uid,
            department_id=dept,
            channel="email",
            topic="Срок изготовления",
            status="closed" if n % 7 else "open",
            priority="medium",
            created_at=opened,
            first_response_at=opened + timedelta(hours=1),
            closed_at=closed if n % 7 else None,
            sla_deadline=opened + timedelta(hours=24),
            resolution="Клиенту сообщён срок" if n % 7 else None,
            cause="Задержка ответа" if n % 5 == 0 else None,
        )
