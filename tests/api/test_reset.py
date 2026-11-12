from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import AuditLog, DecisionHistory, Order, Task, User


async def test_demo_restore_preserves_credentials_and_immutable_history(
    client, database, seeded, monkeypatch
):
    login = await client.post(
        "/api/v1/auth/login", json={"email": "admin@fotoprint.demo", "password": "SeedPassword123!"}
    )
    headers = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
    config = get_settings()
    monkeypatch.setattr(config, "demo_mode", True)
    async with database() as db:
        order = await db.scalar(select(Order).where(Order.external_id == "ERP-O-1"))
        expected = order.amount
        order.amount = 999
        before_history = await db.scalar(select(func.count()).select_from(DecisionHistory))
        before_audit = await db.scalar(select(func.count()).select_from(AuditLog))
        employee = await db.scalar(select(User).where(User.role == "employee"))
        password_hash = employee.password_hash
        await db.commit()
    response = await client.post("/api/v1/demo/reset", headers=headers, json={"confirm": "RESET_DEMO_DATA"})
    assert response.status_code == 200, response.text
    async with database() as db:
        order = await db.scalar(select(Order).where(Order.external_id == "ERP-O-1"))
        assert order.amount == expected
        employee = await db.scalar(select(User).where(User.role == "employee"))
        assert employee.password_hash == password_hash
        assert await db.scalar(select(func.count()).select_from(DecisionHistory)) > before_history
        assert await db.scalar(select(func.count()).select_from(AuditLog)) > before_audit
        assert (
            await db.scalar(
                select(func.count()).select_from(Task).where(Task.deleted_at.is_(None), Task.status == "new")
            )
            == 3
        )
        assert await db.scalar(select(func.count()).select_from(Order)) == 500
