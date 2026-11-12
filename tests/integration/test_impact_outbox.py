"""Worker delivery, retries and lease recovery against real PostgreSQL."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select

from app.models import User
from app.models.impact import ManagementAction, Notification, NotificationOutbox
from app.schemas.impact import ActionCommand, ActionCreate
from app.schemas.shared.query import BusinessQuery
from app.services.impact import actions, notifications


async def test_outbox_blocked_retry_lease_and_ack_deadline_boundary(database, seeded_database):
    async with database() as db:
        director = await db.scalar(select(User).where(User.email == "director@fotoprint.demo"))
        assignee = await db.scalar(select(User).where(User.email == "employee@fotoprint.demo"))
        obj = await actions.create(
            db,
            ActionCreate(
                type="reminder",
                department_id=assignee.department_id,
                assignee_id=assignee.id,
                title="Worker delivery",
                text="Synthetic integration test",
                priority="critical",
                metric_code="on_time_orders",
                context=BusinessQuery(),
            ),
            director,
            None,
        )
        await actions.command(db, obj, "send", ActionCommand(version=obj.version), director, None)
        action = await actions.out(db, obj, director)
        await db.commit()
    async with database() as db:
        user = await db.get(User, UUID(action["assignee_id"]))
        user.is_active = False
        await db.commit()
    await notifications.tick(database)
    async with database() as db:
        row = await db.scalar(
            select(NotificationOutbox).where(NotificationOutbox.action_id == UUID(action["id"]))
        )
        assert row.status == "pending" and row.attempts == 1 and row.last_error == "RECIPIENT_UNAVAILABLE"
        row.status = "processing"
        row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        user = await db.get(User, UUID(action["assignee_id"]))
        user.is_active = True
        await db.commit()
    await notifications.tick(database)
    await notifications.tick(database)
    async with database() as db:
        row = await db.scalar(
            select(NotificationOutbox).where(NotificationOutbox.action_id == UUID(action["id"]))
        )
        assert row.status == "sent" and row.attempts == 2
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.action_id == UUID(action["id"]))
            )
            == 1
        )
        obj = await db.get(ManagementAction, UUID(action["id"]))
        exact = datetime.now(UTC)
        obj.response_due_at = exact
        obj.acknowledged_at = exact
        obj.status = "acknowledged"
        await notifications.scan_sla(db, now=exact + timedelta(seconds=1))
        await db.refresh(obj)
        assert not (
            await __import__("app.services.impact.actions", fromlist=["out"]).out(
                db, obj, type("R", (), {"role": "admin", "id": None})()
            )
        )["response_was_late"]
        assert (
            await db.scalar(
                select(func.count())
                .select_from(NotificationOutbox)
                .where(
                    NotificationOutbox.action_id == obj.id, NotificationOutbox.kind == "escalation_response"
                )
            )
            == 0
        )
