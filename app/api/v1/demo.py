from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, text

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.permissions import require_role
from app.models import (
    Alert,
    Customer,
    Decision,
    DecisionHistory,
    FinanceRecord,
    MetricValue,
    Order,
    Product,
    ProductionRecord,
    SourceRecord,
    SupportInteraction,
    Task,
)
from app.schemas.common import Data, Schema
from app.seed.service import identifier, seed
from app.services.audit import record
from app.services.serialization import columns

router = APIRouter(tags=["demo"])


class Reset(Schema):
    confirm: Literal["RESET_DEMO_DATA"]


class ResetResult(Schema):
    success: Literal[True]
    seeded_at: datetime
    mode: Literal["restore_demo_fixtures"]
    archived_tasks: int
    cancelled_decisions: int


@router.post("/demo/reset", response_model=Data[ResetResult])
async def reset(payload: Reset, request: Request, db: DB, user: CurrentUser):
    config = get_settings()
    if config.app_env == "production":
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Маршрут недоступен")
    require_role(user, {"admin"})
    if not config.demo_mode:
        raise ApiError(403, "AUTH_FORBIDDEN", "Демонстрационный сброс отключён")
    await db.execute(text("SELECT pg_advisory_xact_lock(178901234)"))
    # Refuse to erase or reinterpret unknown source data, even in a development database.
    provenances = (await db.scalars(select(SourceRecord))).all()
    trusted = {
        row.platform_id
        for row in provenances
        if row.id == identifier(f"provenance:{row.source_name}:{row.entity_type}:{row.platform_id}")
    }
    for model in [Customer, Product, Order, ProductionRecord, FinanceRecord, SupportInteraction]:
        identifiers = (await db.scalars(select(model.id))).all()
        if any(uid not in trusted for uid in identifiers):
            raise ApiError(
                409,
                "DEMO_DATA_NOT_ISOLATED",
                "Есть записи вне известного синтетического набора; безопасный сброс отклонён",
            )
    passwords = {
        role: getattr(config, "demo_" + role + "_password").get_secret_value()
        if getattr(config, "demo_" + role + "_password")
        else ""
        for role in ["admin", "director", "manager", "analyst", "employee"]
    }
    if any(len(value) < 12 for value in passwords.values()):
        raise ApiError(409, "DEMO_CONFIGURATION_INCOMPLETE", "Для восстановления задайте DEMO_*_PASSWORD")
    now = datetime.now(UTC)
    archived = 0
    cancelled = 0
    for task in (await db.scalars(select(Task).where(Task.deleted_at.is_(None)))).all():
        before = columns(task)
        task.deleted_at = now
        task.version += 1
        task.updated_at = now
        archived += 1
        record(
            db,
            "task.archived",
            "task",
            actor=user,
            object_id=task.id,
            old=before,
            new=columns(task),
            details={"reason": "demo.reset"},
            request=request,
        )
    for decision in (
        await db.scalars(select(Decision).where(Decision.status.not_in(["completed", "cancelled"])))
    ).all():
        before = columns(decision)
        decision.status = "cancelled"
        decision.version += 1
        decision.updated_at = now
        cancelled += 1
        db.add(
            DecisionHistory(
                decision_id=decision.id,
                changed_by=user.id,
                action="demo.reset",
                old_values=jsonable_encoder(before),
                new_values=jsonable_encoder(columns(decision)),
                comment="Архивация перед восстановлением демосценария",
            )
        )
        record(
            db,
            "demo.reset",
            "decision",
            actor=user,
            object_id=decision.id,
            old=before,
            new=columns(decision),
            request=request,
        )
    await seed(db, passwords=passwords, restore=True)
    # Explicit maintenance restoration is separate from normal recalculation/reopening rules.
    for alert in (await db.scalars(select(Alert))).all():
        latest = await db.get(MetricValue, alert.metric_value_id) if alert.metric_value_id else None
        target = "active" if latest and latest.status == "critical" else "resolved"
        if alert.status != target:
            before = {"status": alert.status}
            alert.status = target
            alert.updated_at = now
            record(
                db,
                "demo.reset",
                "alert",
                actor=user,
                object_id=alert.id,
                old=before,
                new={"status": target},
                request=request,
            )
    record(
        db,
        "demo.reset",
        "demo",
        actor=user,
        details={
            "mode": "restore_demo_fixtures",
            "archived_tasks": archived,
            "cancelled_decisions": cancelled,
        },
        request=request,
    )
    await db.commit()
    return {
        "data": {
            "success": True,
            "seeded_at": now,
            "mode": "restore_demo_fixtures",
            "archived_tasks": archived,
            "cancelled_decisions": cancelled,
        }
    }
