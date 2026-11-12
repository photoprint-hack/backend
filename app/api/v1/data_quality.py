from types import SimpleNamespace
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.permissions import require_role
from app.models import DataQualityIssue, DataQualityRun, SourceSyncRun
from app.schemas.common import Data, Page, Schema, page
from app.schemas.integrations.imports import ImportRun, SourceStatus
from app.schemas.integrations.quality import QualityCheckResult, QualityIssue, QualityOverview, Reconciliation
from app.schemas.shared.query import BusinessQuery
from app.services.data_quality import SOURCES, check, reconciliation, source_status
from app.services.serialization import columns

router = APIRouter(tags=["data-quality"])


def quality_role(user, *, full=False):
    require_role(user, {"admin", "analyst"} if full else {"admin", "director", "analyst"})


class Check(Schema):
    source: Literal["crm", "erp", "finance", "support", "hr"] | None = None


class IssuesQuery(Schema):
    page: int = Query(1, ge=1)
    page_size: int = Query(20, ge=1, le=100)
    source: Literal["crm", "erp", "finance", "support", "hr"] | None = None
    check_type: (
        Literal[
            "missing_fields",
            "duplicates",
            "invalid_values",
            "broken_relations",
            "financial_reconciliation",
            "stale_source",
        ]
        | None
    ) = None
    severity: Literal["warning", "critical"] | None = None
    status: Literal["open", "resolved"] | None = None
    department_id: UUID | None = None


class ListQuery(Schema):
    page: int = Query(1, ge=1)
    page_size: int = Query(20, ge=1, le=100)


@router.get("/data-quality/sources", response_model=Page[SourceStatus])
@router.get("/integrations", response_model=Page[SourceStatus])
async def sources(db: DB, user: CurrentUser, query: Annotated[ListQuery, Query()]):
    quality_role(user)
    items = []
    for source in SOURCES:
        item = await source_status(db, source)
        item["id"] = uuid5(NAMESPACE_URL, "photoprint:source:" + source)
        items.append(item)
    return page(
        items[(query.page - 1) * query.page_size : query.page * query.page_size],
        len(items),
        query.page,
        query.page_size,
    )


@router.get("/data-quality/overview", response_model=Data[QualityOverview])
async def overview(db: DB, user: CurrentUser):
    quality_role(user)
    states = [await source_status(db, source) for source in SOURCES]
    latest = await db.scalar(select(DataQualityRun).order_by(DataQualityRun.checked_at.desc()).limit(1))
    open_count = await db.scalar(
        select(func.count()).select_from(DataQualityIssue).where(DataQualityIssue.status == "open")
    )
    critical = await db.scalar(
        select(func.count())
        .select_from(DataQualityIssue)
        .where(DataQualityIssue.status == "open", DataQualityIssue.severity == "critical")
    )
    result = await reconciliation(
        db, SimpleNamespace(date_from=None, date_to=None, department_id=None, product_id=None)
    )
    return {
        "data": {
            "checked_at": latest.checked_at if latest else None,
            "last_run_id": latest.id if latest else None,
            "sources_total": len(states),
            "healthy_sources": sum(x["status"] == "healthy" for x in states),
            "stale_sources": sum(x["is_stale"] or x["status"] == "not_loaded" for x in states),
            "open_issues": open_count,
            "critical_issues": critical,
            "reconciliation": result,
        }
    }


@router.get("/data-quality/issues", response_model=Page[QualityIssue])
async def issues(db: DB, user: CurrentUser, query: Annotated[IssuesQuery, Query()]):
    quality_role(user, full=True)
    stmt = select(DataQualityIssue)
    for field in ["check_type", "severity", "status", "department_id"]:
        value = getattr(query, field)
        if value is not None:
            stmt = stmt.where(getattr(DataQualityIssue, field) == value)
    if query.source:
        stmt = stmt.where(DataQualityIssue.source_name == query.source)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.scalars(
            stmt.order_by(DataQualityIssue.checked_at.desc(), DataQualityIssue.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    return page(
        [
            {
                **columns(row, exclude={"source_name", "fingerprint", "details"}),
                "source": row.source_name,
                "links": [],
            }
            for row in rows
        ],
        total,
        query.page,
        query.page_size,
    )


@router.post("/data-quality/check", response_model=Data[QualityCheckResult])
async def run_check(payload: Check, request: Request, db: DB, user: CurrentUser):
    quality_role(user, full=True)
    result = await check(db, user, payload.source, request)
    await db.commit()
    return {"data": result}


@router.get("/data-quality/reconciliation", response_model=Data[Reconciliation])
async def reconcile(db: DB, user: CurrentUser, query: Annotated[BusinessQuery, Query()]):
    quality_role(user)
    return {"data": await reconciliation(db, query)}


def import_result(run, *, errors=False):
    item = {
        "run_id": run.id,
        "source": run.source_name,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "received": run.records_received,
        "inserted": run.records_inserted,
        "updated": run.records_updated,
        "skipped": run.records_skipped,
        "failed": run.records_failed,
        "errors_total": len(run.errors),
        "recalculation_status": run.recalculation_status,
        "recalculation_error": run.recalculation_error,
    }
    if errors:
        item["errors"] = run.errors[:100]
    return item


@router.get("/integrations/history", name="all_import_history", response_model=Page[ImportRun])
async def all_history(db: DB, user: CurrentUser, query: Annotated[ListQuery, Query()]):
    quality_role(user, full=True)
    stmt = select(SourceSyncRun)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.scalars(
            stmt.order_by(SourceSyncRun.started_at.desc())
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    return page([import_result(row) for row in rows], total, query.page, query.page_size)


@router.get("/integrations/{source}/history", response_model=Page[ImportRun])
async def history(
    source: Literal["crm", "erp", "finance", "support", "hr"],
    db: DB,
    user: CurrentUser,
    query: Annotated[ListQuery, Query()],
):
    quality_role(user, full=True)
    stmt = select(SourceSyncRun).where(SourceSyncRun.source_name == source)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.scalars(
            stmt.order_by(SourceSyncRun.started_at.desc())
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    return page([import_result(row) for row in rows], total, query.page, query.page_size)


@router.get("/data-quality/sources/{source}", response_model=Data[SourceStatus])
@router.get("/integrations/{source}", response_model=Data[SourceStatus])
async def source(db: DB, user: CurrentUser, source: Literal["crm", "erp", "finance", "support", "hr"]):
    quality_role(user)
    item = await source_status(db, source)
    item["id"] = uuid5(NAMESPACE_URL, "photoprint:source:" + source)
    return {"data": item}
