import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.permissions import READ_ROLES, require_role
from app.models import DataQualityIssue
from app.models.impact import AIAnalysis
from app.schemas.impact import AnalysisContent, AnalysisOut
from app.services import idempotency
from app.services.impact import graph, provider, responsibility

PROMPT_VERSION = "impact-analysis-v1"


async def context_for(db, payload, user):
    require_role(user, READ_ROLES)
    if not user.is_active:
        raise ApiError(403, "AUTH_FORBIDDEN", "Пользователь заблокирован")
    full = await graph.build(db, payload.context, user)
    if full["graph_revision"] != payload.graph_revision:
        raise ApiError(409, "CONTEXT_STALE", "Обновите карту: исходные данные изменились")
    node = next(
        (n for n in full["nodes"] if n["entity_ref"] == {"type": "metric", "id": payload.metric_code}), None
    )
    if not node:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "KPI недоступен")
    sub = graph.explore(full, node["id"], 1)
    # No business text, customer identities, conversations or names go to the provider.
    safe_nodes = [{"id": n["id"], "type": n["type"], "status": n["status"]} for n in sub["nodes"]]
    facts = [
        {
            "text": f"{node['label']}: факт={node['metadata']['kpi']['actual']}; план={node['metadata']['kpi']['target']}; статус={node['status']}",
            "refs": [node["id"]],
        }
    ]
    dependencies = [
        {"text": e["description"], "refs": [e["source"], e["target"]]}
        for e in sub["edges"]
        if e["evidence_type"] == "calculated"
    ]
    stmt = select(DataQualityIssue).where(DataQualityIssue.status == "open")
    department = full["context"]["department_id"]
    if department:
        stmt = stmt.where(DataQualityIssue.department_id == department)
    quality = [
        {
            "source": x.source_name,
            "check_type": x.check_type,
            "severity": x.severity,
            "affected_records": x.affected_records,
        }
        for x in (await db.scalars(stmt.order_by(DataQualityIssue.id).limit(20))).all()
    ]
    owner = await responsibility.default_recipient(db, payload.metric_code, department)
    if owner:
        try:
            await responsibility.recipient(db, owner, department)
        except ApiError:
            owner = None
    return {
        "context": full["context"],
        "graph_revision": full["graph_revision"],
        "metric": node["metadata"],
        "nodes": safe_nodes,
        "edges": [
            {key: edge[key] for key in ("source", "target", "type", "evidence_type")} for edge in sub["edges"]
        ],
        "verified_facts": facts,
        "calculated_dependencies": dependencies,
        "quality": quality,
        "suggested_responsible": str(owner) if owner else None,
    }


def validated(content, context):
    try:
        value = AnalysisContent.model_validate(content).model_dump()
    except ValueError:
        raise ApiError(503, "AI_UNAVAILABLE", "Модель вернула неверный формат анализа") from None
    allowed = {n["id"] for n in context["nodes"]}
    for field in (
        "changes",
        "verified_facts",
        "calculated_dependencies",
        "correlations",
        "hypotheses",
        "possible_impacts",
        "recommendations",
        "data_gaps",
    ):
        for item in value[field]:
            if not set(item["refs"]) <= allowed:
                raise ApiError(503, "AI_UNAVAILABLE", "AI сослался на недоступные данные")
    # Only server-owned assertions can appear as evidence. Model assertions stay generative.
    value["verified_facts"] = context["verified_facts"]
    value["calculated_dependencies"] = context["calculated_dependencies"]
    value["correlations"] = []
    value["suggested_responsible"] = context["suggested_responsible"]
    return value


def output(row, context, cached):
    return AnalysisOut(
        id=row.id,
        analysis=row.payload,
        context=context["context"],
        graph_revision=context["graph_revision"],
        model=row.model,
        generated_at=row.created_at,
        cached=cached,
    ).model_dump(mode="json")


async def analyze(db, payload, user):
    context = await context_for(db, payload, user)
    config = get_settings()
    now = datetime.now(UTC)
    epoch = int(now.timestamp()) // config.ai_cache_ttl_seconds
    request_hash = graph.digest(payload)
    cache_key = graph.digest(
        [
            str(user.id),
            user.role,
            str(user.department_id),
            PROMPT_VERSION,
            config.openrouter_model,
            context,
            epoch,
        ]
    )
    replay, request_digest = await idempotency.begin(db, user, payload.request_key, "impact.analyze", payload)
    if replay:
        # Revalidate the context and role before returning a saved result.
        saved = replay.response_body["data"]
        cached_analysis = await db.get(AIAnalysis, UUID(saved["id"]))
        if not cached_analysis or cached_analysis.cache_key != cache_key:
            raise ApiError(
                409, "CONTEXT_STALE", "Роль, область или срок кэша изменились; используйте новый request_key"
            )
        if saved["graph_revision"] != context["graph_revision"]:
            raise ApiError(409, "CONTEXT_STALE", "Обновите карту")
    previous = await db.scalar(
        select(AIAnalysis).where(AIAnalysis.user_id == user.id, AIAnalysis.request_key == payload.request_key)
    )
    if previous and previous.cache_key != cache_key:
        raise ApiError(409, "CONTEXT_STALE", "Контекст доступа или срок кэша изменился")
    if previous and previous.request_hash != request_hash:
        raise ApiError(409, "IDEMPOTENCY_CONFLICT", "Request key использован с другим контекстом")
    await db.execute(text("SELECT pg_advisory_xact_lock(178901236)"))
    now = datetime.now(UTC)
    if previous and previous.expires_at <= now:
        raise ApiError(409, "CONTEXT_STALE", "Срок анализа истёк; используйте новый request_key")
    row = previous or await db.scalar(select(AIAnalysis).where(AIAnalysis.cache_key == cache_key))
    if row and row.status == "completed" and row.expires_at > now:
        result = output(row, context, True)
        if not replay:
            idempotency.remember(
                db,
                user,
                payload.request_key,
                "impact.analyze",
                request_digest,
                {"data": result},
                status_code=200,
            )
        await db.commit()
        return result
    if row and row.status == "pending" and row.lease_until > now:
        # The only provider call is owned by the reservation; wait without holding a DB transaction.
        identifier = row.id
        await db.rollback()
        for _ in range(config.ai_timeout_seconds * 5 + 10):
            await asyncio.sleep(0.2)
            row = await db.scalar(
                select(AIAnalysis)
                .where(AIAnalysis.id == identifier)
                .execution_options(populate_existing=True)
            )
            if row and row.status != "pending":
                await db.refresh(user)
                context = await context_for(db, payload, user)
                if row.status == "completed":
                    result = output(row, context, True)
                    existing, request_digest = await idempotency.begin(
                        db, user, payload.request_key, "impact.analyze", payload
                    )
                    if not existing:
                        idempotency.remember(
                            db,
                            user,
                            payload.request_key,
                            "impact.analyze",
                            request_digest,
                            {"data": result},
                            status_code=200,
                        )
                    await db.commit()
                    return result
                raise ApiError(
                    429 if row.error_code == "AI_RATE_LIMITED" else 503,
                    row.error_code or "AI_UNAVAILABLE",
                    "AI-анализ недоступен",
                )
            await db.rollback()
        raise ApiError(503, "AI_UNAVAILABLE", "Анализ ещё не завершён; повторите с тем же request_key")
    if not config.openrouter_api_key:
        raise ApiError(503, "AI_UNAVAILABLE", "OpenRouter не настроен")
    budget = await db.scalar(
        select(func.count())
        .select_from(AIAnalysis)
        .where(AIAnalysis.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0))
    )
    if budget >= min(config.ai_daily_budget, 40):
        raise ApiError(429, "AI_RATE_LIMITED", "Дневной бюджет демо исчерпан")
    if row:
        # A failed/expired reservation does not trigger an implicit retry against the free quota.
        raise ApiError(
            429 if row.error_code == "AI_RATE_LIMITED" else 503,
            row.error_code or "AI_UNAVAILABLE",
            "Предыдущая попытка завершена; дождитесь нового контекста или истечения кэша",
        )
    row = AIAnalysis(
        user_id=user.id,
        cache_key=cache_key,
        request_key=payload.request_key,
        request_hash=request_hash,
        status="pending",
        expires_at=now + timedelta(seconds=config.ai_cache_ttl_seconds),
        lease_until=now + timedelta(seconds=config.ai_timeout_seconds + 10),
    )
    db.add(row)
    await db.flush()
    identifier = row.id
    await db.commit()
    # No transaction or row lock is held while an external request is in flight.
    try:
        content, model = await provider.generate(jsonable_encoder(context))
        value = validated(content, context)
    except ApiError as error:
        row = await db.get(AIAnalysis, identifier)
        row.status, row.error_code = "failed", error.code
        await db.commit()
        raise
    row = await db.get(AIAnalysis, identifier)
    row.status, row.payload, row.model = "completed", value, model
    await db.commit()
    await db.refresh(user)
    context = await context_for(db, payload, user)
    result = output(row, context, False)
    existing, request_digest = await idempotency.begin(
        db, user, payload.request_key, "impact.analyze", payload
    )
    if not existing:
        idempotency.remember(
            db, user, payload.request_key, "impact.analyze", request_digest, {"data": result}, status_code=200
        )
    await db.commit()
    return result
