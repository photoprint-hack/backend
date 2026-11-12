from datetime import datetime, time, timedelta
from decimal import Decimal

from app.core.security import hash_password
from app.models import (
    Campaign,
    Customer,
    Department,
    Product,
    User,
)
from app.seed.context import SeedContext, identifier


async def seed_catalog(ctx: SeedContext):
    db = ctx.db
    known = ctx.known
    passwords = ctx.passwords
    reference = ctx.reference
    zone = ctx.zone
    add = ctx.add
    departments = []
    for code, name in [("sales", "Продажи"), ("production", "Производство"), ("support", "Поддержка")]:
        departments.append(add(Department, "department:" + code, code=code, name=name, is_active=True))
    await db.flush()
    people = {}
    for role, name in [
        ("admin", "Демо Администратор"),
        ("director", "Демо Директор"),
        ("manager", "Демо Руководитель"),
        ("analyst", "Демо Аналитик"),
        ("employee", "Демо Исполнитель"),
    ]:
        uid = identifier("user:" + role)
        if uid not in known[User]:
            from starlette.concurrency import run_in_threadpool

            hashed = await run_in_threadpool(hash_password, passwords[role])
            add(
                User,
                "user:" + role,
                email=role + "@fotoprint.demo",
                password_hash=hashed,
                full_name=name,
                role=role,
                department_id=departments[0] if role in {"manager", "employee"} else None,
                is_active=True,
            )
        people[role] = uid
    products = []
    for n, name in enumerate(["Фотокнига", "Фотопечать", "Холст", "Календарь", "Открытки"]):
        products.append(
            add(
                Product,
                f"product:{n}",
                external_id=f"ERP-P-{n}",
                code=f"product_{n}",
                name=name,
                category="photoproduct",
                standard_price=Decimal(50 + n * 25),
                currency="BYN",
                standard_hours_per_unit=Decimal("0.1") * (n + 1),
                is_active=True,
            )
        )
    await db.flush()
    campaigns = []
    for n in range(5):
        campaigns.append(
            add(
                Campaign,
                f"campaign:{n}",
                external_id=f"CRM-CMP-{n}",
                name=f"Демо кампания {n + 1}",
                channel=["website", "email", "social"][n % 3],
                segment="retail",
                budget=Decimal(1000),
                currency="BYN",
                started_at=datetime.combine(reference - timedelta(days=90), time(0), zone),
                ended_at=None,
            )
        )
    customers = []
    for n in range(200):
        customers.append(
            add(
                Customer,
                f"customer:{n}",
                external_id=f"CRM-C-{n}",
                name=f"Клиент {n + 1:03}",
                customer_type="b2b" if n % 4 == 0 else "b2c",
                segment="corporate" if n % 4 == 0 else "retail",
                acquisition_channel=["website", "email", "social"][n % 3],
            )
        )
    await db.flush()
    ctx.departments = departments
    ctx.people = people
    ctx.products = products
    ctx.campaigns = campaigns
    ctx.customers = customers
