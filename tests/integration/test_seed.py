"""Seed repeatability and persistence without exercising HTTP endpoints."""

from sqlalchemy import func, select

from app.models import Alert, Decision, Order, Task, User
from app.seed.service import seed


async def test_reseed_does_not_duplicate_or_overwrite_work(database, seeded_database):
    async with database() as db:
        before = {
            model: await db.scalar(select(func.count()).select_from(model))
            for model in [Order, Alert, Decision, Task]
        }
        task = await db.scalar(select(Task))
        task.status = "in_progress"
        task.version = 2
        user = await db.scalar(select(User).where(User.role == "employee"))
        old = user.password_hash
        await db.commit()
        await seed(
            db,
            passwords=dict.fromkeys(
                ["admin", "director", "manager", "analyst", "employee"], "ChangedPassword123!"
            ),
        )
        await db.commit()
        for model, count in before.items():
            assert await db.scalar(select(func.count()).select_from(model)) == count
        await db.refresh(task)
        await db.refresh(user)
        assert task.status == "in_progress"
        assert user.password_hash == old
