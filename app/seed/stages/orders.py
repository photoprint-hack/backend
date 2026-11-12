from datetime import datetime, time, timedelta
from decimal import Decimal

from app.models import (
    Customer,
    Deal,
    DealEvent,
    FinanceRecord,
    Order,
    OrderEvent,
    ProductionRecord,
)
from app.seed.context import SeedContext, identifier


async def seed_orders(ctx: SeedContext):
    campaigns = ctx.campaigns
    customers = ctx.customers
    db = ctx.db
    departments = ctx.departments
    known = ctx.known
    products = ctx.products
    reference = ctx.reference
    restore = ctx.restore
    zone = ctx.zone
    add = ctx.add
    orders = []
    firsts = {}
    for n in range(500):
        # All completed facts precede the reference date; no future completion timestamps.
        event_date = reference - timedelta(days=1 + n % 84)
        created = datetime.combine(event_date, time(8), zone)
        completed = created + timedelta(hours=4 + n % 12)
        status = (
            "cancelled"
            if n % 17 == 0
            else "in_progress"
            if n % 11 == 0
            else "new"
            if n % 19 == 0
            else "completed"
        )
        dept = departments[n % 3]
        product = products[n % 5]
        customer = customers[n % 200]
        amount = Decimal(100 + (n % 20) * 25)
        quantity = 5 + n % 20
        deadline = created + timedelta(hours=8)
        uid = add(
            Order,
            f"order:{n}",
            external_id=f"ERP-O-{n}",
            order_number=f"FP-DEMO-{n + 1:06}",
            customer_id=customer,
            product_id=product,
            department_id=dept,
            campaign_id=campaigns[n % 5],
            channel=["website", "email", "social"][n % 3],
            quantity=quantity,
            standard_hours_per_unit=Decimal("0.1") * (n % 5 + 1),
            amount=amount,
            currency="BYN",
            status=status,
            moderation_status="approved" if status != "new" else "pending",
            production_status="completed" if status == "completed" else "queued",
            delivery_status="delivered" if status == "completed" else "not_started",
            has_defect=n % 9 == 0,
            due_at=deadline,
            completed_at=completed if status == "completed" else None,
            created_at=created,
            updated_at=completed,
            version=1,
            source_system="erp",
        )
        orders.append((uid, dept, product, customer, created, completed, status, amount, quantity))
        if status == "completed":
            firsts[customer] = min(firsts.get(customer, completed), completed)
    await db.flush()
    for customer, first in firsts.items():
        obj = await db.get(Customer, customer)
        if obj.first_order_at is None or restore:
            obj.first_order_at = first
    for n, (uid, dept, product, customer, created, completed, status, amount, quantity) in enumerate(orders):
        stage = (
            "won"
            if status == "completed"
            else "lost"
            if status == "cancelled"
            else ["new", "qualified", "proposal"][n % 3]
        )
        deal = add(
            Deal,
            f"deal:{n}",
            external_id=f"CRM-D-{n}",
            customer_id=customer,
            product_id=product,
            department_id=dept,
            campaign_id=campaigns[n % 5],
            channel=["website", "email", "social"][n % 3],
            segment="retail",
            stage=stage,
            expected_amount=amount,
            currency="BYN",
            order_id=uid if stage == "won" else None,
            created_at=created,
            updated_at=completed,
        )
        await db.flush()
        if identifier(f"order:{n}") in known[Order]:
            order = await db.get(Order, uid)
            if order.crm_deal_id is None:
                order.crm_deal_id = deal
        stages = (
            ["new", "qualified", "proposal", "won"]
            if stage == "won"
            else ["new", "lost"]
            if stage == "lost"
            else ["new", "qualified", "proposal"][: ["new", "qualified", "proposal"].index(stage) + 1]
        )
        for i, value in enumerate(stages):
            add(
                DealEvent,
                f"deal_event:{n}:{i}",
                deal_id=deal,
                old_stage=stages[i - 1] if i else None,
                new_stage=value,
                occurred_at=created + timedelta(minutes=i),
            )
        add(
            OrderEvent,
            f"order_event:{n}:create",
            order_id=uid,
            event_type="order_created",
            old_status=None,
            new_status="new",
            department_id=dept,
            source_system="erp",
            result="Заказ получен из синтетического ERP",
            occurred_at=created,
        )
        if status == "completed":
            add(
                OrderEvent,
                f"order_event:{n}:complete",
                order_id=uid,
                event_type="production_completed",
                old_status="in_progress",
                new_status="completed",
                department_id=dept,
                source_system="erp",
                result="Производство завершено",
                occurred_at=completed,
            )
            add(
                FinanceRecord,
                f"finance:{n}:revenue",
                external_id=f"FIN-R-{n}",
                department_id=dept,
                product_id=product,
                order_id=uid,
                record_date=completed.astimezone(zone).date(),
                record_type="revenue",
                amount=amount,
                currency="BYN",
            )
            add(
                FinanceRecord,
                f"finance:{n}:cost",
                external_id=f"FIN-C-{n}",
                department_id=dept,
                product_id=product,
                order_id=uid,
                record_date=completed.astimezone(zone).date(),
                record_type="direct_cost",
                amount=(amount * Decimal("0.78")).quantize(Decimal("0.01")),
                currency="BYN",
            )
            add(
                ProductionRecord,
                f"production:{n}",
                external_id=f"ERP-PR-{n}",
                order_id=uid,
                department_id=dept,
                product_id=product,
                production_date=completed.astimezone(zone).date(),
                planned_quantity=quantity,
                actual_quantity=quantity,
                defective_quantity=2 if n % 9 == 0 else 0,
                reprint_quantity=2 if n % 9 == 0 else 0,
                queue_quantity=0,
                downtime_minutes=15 if n % 9 == 0 else 0,
                actual_load_hours=Decimal(quantity) * Decimal("0.1") * (n % 5 + 1),
                lead_time_hours=Decimal(4 + n % 12),
                cause="Сбой цветопередачи" if n % 9 == 0 else None,
            )
    await db.flush()
    ctx.orders = orders
