"""Preserve source facts for company readers and an independent department snapshot for managers."""

from fastapi.encoders import jsonable_encoder

from app.core.exceptions import ApiError
from app.schemas.shared.query import BusinessQuery
from app.services import analytics


async def capture(db, query, code, user):
    kpis, context = await analytics.calculate(db, query, user)
    if code:
        kpi = next((value for value in kpis if value["code"] == code), None)
        if not kpi:
            raise ApiError(404, "RESOURCE_NOT_FOUND", "KPI не найден")
        context["problem"] = {
            name: kpi[name] for name in ("code", "actual", "target", "status", "source_updated_at")
        }
    return jsonable_encoder(context)


async def capture_pair(db, payload, user):
    source = await capture(db, payload.context, payload.metric_code, user)
    if source["department_id"] == str(payload.department_id):
        return source, source.copy()
    department_query = BusinessQuery(
        date_from=source["date_from"],
        date_to=source["date_to"],
        product_id=payload.context.product_id,
        department_id=payload.department_id,
    )
    department = await capture(db, department_query, payload.metric_code, user)
    return source, department


def replay_allowed(body, user):
    """A replay may preserve an older representation only while it remains authorized."""
    if user.role == "manager" and body["data"]["context"].get("department_id") != str(user.department_id):
        raise ApiError(
            403,
            "AUTH_FORBIDDEN",
            "Сохранённый ответ содержит контекст прежних прав; откройте карточку заново",
        )
    if user.role == "employee" and body["data"].get("metric_code"):
        raise ApiError(403, "AUTH_FORBIDDEN", "Сохранённый ответ относится к прежним правам")
