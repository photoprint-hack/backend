from typing import Annotated, Literal

from fastapi import APIRouter, Request
from pydantic import Field

from app.api.deps import DB, CurrentUser
from app.api.v1.data_quality import import_result
from app.core.exceptions import ApiError
from app.core.permissions import require_role
from app.schemas.common import Data, Schema
from app.schemas.integrations.imports import ImportResult
from app.services.imports import import_records

router = APIRouter(tags=["integrations"])


class ImportBatch(Schema):
    records: Annotated[list[dict], Field(max_length=1000)]


@router.post("/integrations/{source}/import", response_model=Data[ImportResult])
async def run_import(
    source: Literal["crm", "erp", "finance", "support", "hr"],
    payload: ImportBatch,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    require_role(user, {"admin"})
    if len(await request.body()) > 5 * 1024 * 1024:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "Максимальный размер пакета — 5 MiB")
    result = await import_records(db, source, payload.records, user, request)
    return {"data": import_result(result, errors=True)}
