"""Synthetic responsibility/action/Mary examples. Normal reseed preserves all user work."""

from datetime import timedelta

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core.security import hash_password
from app.models import Metric, SourceRecord, Task, User
from app.models.impact import DepartmentResponsibility, ManagementAction, MaryEvent, MetricResponsibility
from app.schemas.impact import ActionCommand, ActionCreate
from app.schemas.shared.query import BusinessQuery
from app.seed.context import identifier
from app.services.impact import actions
from app.services.impact.graph import digest


async def seed_impact(ctx):
    db = ctx.db
    production = ctx.departments[1]
    manager_id = identifier("user:production-manager")
    if not await db.get(User, manager_id):
        db.add(
            User(
                id=manager_id,
                email="production.manager@fotoprint.demo",
                full_name="Демо Руководитель производства",
                role="manager",
                department_id=production,
                is_active=True,
                password_hash=await run_in_threadpool(hash_password, ctx.passwords["manager"]),
            )
        )
        await db.flush()
        ctx.inserted += 1
    heads = [ctx.people["manager"], manager_id, ctx.people["admin"]]
    for department, head in zip(ctx.departments, heads, strict=True):
        if not await db.scalar(
            select(DepartmentResponsibility.id).where(DepartmentResponsibility.department_id == department)
        ):
            db.add(
                DepartmentResponsibility(
                    department_id=department, head_id=head, director_id=ctx.people["director"]
                )
            )
        for code in (await db.scalars(select(Metric.code))).all():
            if not await db.scalar(
                select(MetricResponsibility.id).where(
                    MetricResponsibility.metric_code == code, MetricResponsibility.department_id == department
                )
            ):
                db.add(MetricResponsibility(metric_code=code, department_id=department, owner_id=head))
    for code in (await db.scalars(select(Metric.code))).all():
        if not await db.scalar(
            select(MetricResponsibility.id).where(
                MetricResponsibility.metric_code == code, MetricResponsibility.department_id.is_(None)
            )
        ):
            db.add(
                MetricResponsibility(metric_code=code, department_id=None, owner_id=ctx.people["director"])
            )
    await db.flush()
    director = await db.get(User, ctx.people["director"])
    for index, label in enumerate(
        ["Просроченная реакция", "Просроченное исполнение", "Не назначен получатель"]
    ):
        title = "Демо обращение: " + label
        exists = await db.scalar(select(ManagementAction.id).where(ManagementAction.title == title))
        if exists and not ctx.restore:
            continue
        payload = ActionCreate(
            type="task" if index < 2 else "explanation_request",
            department_id=production,
            title=title,
            text="Синтетический пример для проверки управленческого цикла",
            priority="critical",
            assignee_id=manager_id if index < 2 else None,
            metric_code="on_time_orders",
            context=BusinessQuery(department_id=production),
            execution_due_at=ctx.now + timedelta(days=1) if index < 2 else None,
        )
        obj = await actions.create(db, payload, director, None)
        if index == 2:
            obj.assignee_id = None
        else:
            await actions.command(db, obj, "send", ActionCommand(version=obj.version), director, None)
            obj.sent_at = ctx.now - timedelta(days=7)
            obj.response_due_at = ctx.now - timedelta(days=6)
            # Execution may begin before acknowledge; response SLA is still independent.
            task = await db.get(Task, obj.task_id)
            task.status = "in_progress"
            obj.status = "in_progress"
            if index == 1:
                obj.acknowledged_at = obj.sent_at + timedelta(minutes=1)
                obj.status = "in_progress"
                task = await db.get(Task, obj.task_id)
                task.deadline, task.status = ctx.now - timedelta(days=1), "in_progress"
            actions.event(db, obj, "demo_fixture", director, details={"simulated": True, "scenario": label})
    event_id = identifier("mary:demo:handoff")
    if not await db.get(MaryEvent, event_id):
        department = ctx.departments[0]
        order_id = ctx.orders[0][0]
        db.add(
            MaryEvent(
                id=event_id,
                external_id="MARY-DEMO-1",
                event_type="conversation_handoff",
                occurred_at=ctx.now - timedelta(hours=1),
                department_id=department,
                order_id=order_id,
                metadata_safe={"simulated": True, "channel": "demo"},
            )
        )
        db.add(
            SourceRecord(
                source_name="mary",
                entity_type="mary_event",
                external_id="MARY-DEMO-1",
                platform_id=event_id,
                event_at=ctx.now - timedelta(hours=1),
                loaded_at=ctx.now,
                processing_status="processed",
                content_hash=digest("MARY-DEMO-1"),
            )
        )
    await db.flush()
