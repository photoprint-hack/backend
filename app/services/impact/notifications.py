from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from app.core.exceptions import ApiError
from app.models import Task, User
from app.models.impact import DepartmentResponsibility, ManagementAction, Notification, NotificationOutbox
from app.services.impact import actions, responsibility

RETRY_SECONDS = [10, 30, 120, 300, 900]


async def enqueue(db, action, recipient, kind, suffix):
    key = f"{action.id}:{suffix}:{recipient}"
    result = await db.execute(
        insert(NotificationOutbox)
        .values(
            id=uuid4(),
            action_id=action.id,
            recipient_id=recipient,
            kind=kind,
            deduplication_key=key,
            status="pending",
            attempts=0,
            available_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["deduplication_key"])
        .returning(NotificationOutbox.id)
    )
    return result.scalar_one_or_none() is not None


async def escalate(db, obj, kind, user=None, request=None, reason=None, requested_recipient=None):
    recipient = await responsibility.escalation_recipient(db, obj)
    candidates = [recipient] if recipient else []
    suffix = f"escalate:{obj.assignment_cycle}:{kind}"
    if kind == "manual":
        assignment = await db.scalar(
            select(DepartmentResponsibility).where(
                DepartmentResponsibility.department_id == obj.department_id
            )
        )
        if (
            assignment
            and assignment.director_id not in candidates
            and assignment.director_id != obj.assignee_id
        ):
            candidates.append(assignment.director_id)
        if requested_recipient:
            candidates = [requested_recipient] if requested_recipient in candidates else []
    for candidate in candidates:
        try:
            await responsibility.recipient(db, candidate, obj.department_id)
        except ApiError:
            continue
        if not await enqueue(db, obj, candidate, "escalation_" + kind, suffix):
            continue
        await enqueue(db, obj, obj.assignee_id, "overdue_" + kind, suffix + ":" + str(candidate))
        obj.escalation_level += 1
        actions.touch(obj)
        obj.routing_issue = None
        actions.event(
            db,
            obj,
            "escalated",
            user,
            request,
            details={"sla": kind, "recipient_id": candidate, "reason": reason},
        )
        return True
    if not candidates:
        already_reported = obj.routing_issue == "RESPONSIBLE_NOT_CONFIGURED"
        obj.routing_issue = "RESPONSIBLE_NOT_CONFIGURED"
        if not already_reported:
            actions.touch(obj)
            actions.event(
                db, obj, "routing_failed", details={"sla": kind, "reason": "RESPONSIBLE_NOT_CONFIGURED"}
            )
    return False


async def scan_sla(db, now=None):
    now = now or datetime.now(UTC)
    last_id, count = None, 0
    overdue_tasks = select(Task.id).where(
        Task.deleted_at.is_(None), Task.status.in_(["new", "in_progress"]), Task.deadline < now
    )
    while True:
        stmt = select(ManagementAction).where(
            ManagementAction.status.not_in(actions.TERMINAL | {"draft"}),
            or_(
                (ManagementAction.acknowledged_at.is_(None)) & (ManagementAction.response_due_at < now),
                ManagementAction.task_id.in_(overdue_tasks),
            ),
        )
        if last_id:
            stmt = stmt.where(ManagementAction.id > last_id)
        rows = (
            await db.scalars(stmt.order_by(ManagementAction.id).with_for_update(skip_locked=True).limit(100))
        ).all()
        if not rows:
            return count
        last_id = rows[-1].id
        for obj in rows:
            if obj.response_due_at and obj.response_due_at < now and not obj.acknowledged_at:
                if await escalate(db, obj, "response"):
                    count += 1
            task = await db.get(Task, obj.task_id) if obj.task_id else None
            if task and not task.deleted_at and task.status in {"new", "in_progress"} and task.deadline < now:
                if await escalate(db, obj, "execution"):
                    count += 1


async def claim(db, now=None, limit=100):
    now = now or datetime.now(UTC)
    rows = (
        await db.scalars(
            select(NotificationOutbox)
            .where(
                or_(
                    (NotificationOutbox.status == "pending") & (NotificationOutbox.available_at <= now),
                    (NotificationOutbox.status == "processing") & (NotificationOutbox.lease_until <= now),
                )
            )
            .order_by(NotificationOutbox.available_at, NotificationOutbox.id)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
    ).all()
    ids = []
    for row in rows:
        if row.attempts >= len(RETRY_SECONDS) + 1:
            row.status, row.last_error = "failed", "LEASE_RETRIES_EXHAUSTED"
            continue
        ids.append(row.id)
        row.status, row.lease_until = "processing", now + timedelta(seconds=60)
        row.attempts += 1
    return ids


async def materialize(db, identifier):
    row = await db.scalar(
        select(NotificationOutbox).where(NotificationOutbox.id == identifier).with_for_update()
    )
    if not row or row.status != "processing":
        return
    user = await db.get(User, row.recipient_id)
    obj = None
    if user and user.is_active:
        obj = await db.scalar(actions.statement(user).where(ManagementAction.id == row.action_id))
    if not obj:
        row.last_error = "RECIPIENT_UNAVAILABLE"
        row.status = "pending" if row.attempts <= len(RETRY_SECONDS) else "failed"
        row.available_at = datetime.now(UTC) + timedelta(
            seconds=RETRY_SECONDS[min(row.attempts - 1, len(RETRY_SECONDS) - 1)]
        )
        action = await db.get(ManagementAction, row.action_id)
        action.routing_issue = "RECIPIENT_UNAVAILABLE"
        actions.touch(action)
        actions.event(
            db,
            action,
            "notification_failed",
            details={"outbox_id": row.id, "attempt": row.attempts, "error": row.last_error},
        )
        return
    await db.execute(
        insert(Notification)
        .values(
            id=uuid4(),
            outbox_id=row.id,
            action_id=row.action_id,
            recipient_id=row.recipient_id,
            kind=row.kind,
        )
        .on_conflict_do_nothing(index_elements=["outbox_id"])
    )
    row.status, row.lease_until, row.last_error = "sent", None, None
    if obj.routing_issue == "RECIPIENT_UNAVAILABLE" and obj.assignee_id == row.recipient_id:
        obj.routing_issue = None
        actions.touch(obj)
    actions.event(
        db, obj, "notification_sent", details={"outbox_id": row.id, "recipient_id": row.recipient_id}
    )


async def tick(factory):
    async with factory() as db:
        await scan_sla(db)
        ids = await claim(db)
        await db.commit()
    for identifier in ids:
        async with factory() as db:
            await materialize(db, identifier)
            await db.commit()
    return len(ids)
