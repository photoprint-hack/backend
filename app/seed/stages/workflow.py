from datetime import timedelta

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from app.models import (
    Alert,
    Decision,
    Task,
    User,
)
from app.schemas.workflow.decisions import DecisionCreate
from app.schemas.workflow.tasks import TaskCreate
from app.seed.context import SeedContext
from app.services.analytics import recalculate
from app.services.workflow import create


async def seed_workflow(ctx: SeedContext):
    db = ctx.db
    departments = ctx.departments
    now = ctx.now
    orders = ctx.orders
    people = ctx.people
    restore = ctx.restore
    director = await db.get(User, people["director"])
    await recalculate(db, director)
    for index in range(2):
        # Preserve existing work rather than overwriting seeded decisions on repeated runs.
        title = f"Демо решение {index + 1}: проверить отклонение"
        decision = await db.scalar(
            select(Decision).where(Decision.title == title, Decision.created_by == director.id).limit(1)
        )
        alert = await db.scalar(
            select(Alert)
            .where(Alert.department_id == departments[0], Alert.product_id.is_(None))
            .order_by(Alert.metric_code)
            .offset(index)
            .limit(1)
        )
        if not decision:
            decision = await create(
                db,
                Decision,
                DecisionCreate(
                    title=title,
                    problem="Отклонение от демонстрационного плана",
                    impact="Риск задержки выполнения плана",
                    cause="Требуется проверка исходных данных",
                    action="Проверить заказы и производственные ограничения",
                    department_id=departments[0],
                    owner_id=people["manager"],
                    alert_id=alert.id if alert else None,
                    deadline=now + timedelta(days=3 + index),
                    priority="high",
                    expected_result="Причина установлена, корректирующие действия проверены",
                ),
                director,
                None,
            )
        if restore:
            from app.models import DecisionHistory
            from app.services.audit import record
            from app.services.serialization import columns

            before = jsonable_encoder(columns(decision))
            decision.status = "new"
            decision.actual_result = None
            decision.verification_note = None
            decision.completed_at = None
            decision.deadline = now + timedelta(days=3 + index)
            decision.version += 1
            decision.updated_at = now
            db.add(
                DecisionHistory(
                    decision_id=decision.id,
                    changed_by=director.id,
                    action="demo.reset",
                    old_values=before,
                    new_values=jsonable_encoder(columns(decision)),
                    comment="Восстановлен исходный демонстрационный сценарий",
                )
            )
            record(
                db,
                "demo.reset",
                "decision",
                actor=director,
                object_id=decision.id,
                old=before,
                new=columns(decision),
            )
        for ti in range(2 if index == 0 else 1):
            task_title = f"Демо задача {index + 1}.{ti + 1}"
            found = await db.scalar(
                select(Task.id).where(Task.title == task_title, Task.created_by == director.id).limit(1)
            )
            if restore and found:
                from app.services.audit import record
                from app.services.serialization import columns

                task = await db.get(Task, found)
                before = columns(task)
                task.status = "new"
                task.completed_at = None
                task.deleted_at = None
                task.deadline = now + timedelta(days=2 + ti)
                task.version += 1
                task.updated_at = now
                record(
                    db, "demo.reset", "task", actor=director, object_id=task.id, old=before, new=columns(task)
                )
            if not found:
                await create(
                    db,
                    Task,
                    TaskCreate(
                        title=task_title,
                        description="Проверить исходные данные отклонения",
                        department_id=departments[0],
                        assignee_id=people["employee"],
                        decision_id=decision.id,
                        alert_id=decision.alert_id,
                        order_id=orders[0][0],
                        deadline=now + timedelta(days=2 + ti),
                        priority="high",
                    ),
                    director,
                    None,
                )
    await db.flush()
