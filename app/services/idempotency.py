import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, text

from app.core.exceptions import ApiError
from app.models import IdempotencyKey


async def begin(db, user, key, operation, payload):
    if key is None:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Требуется заголовок Idempotency-Key")
    if key.version != 4:
        raise ApiError(422, "VALIDATION_ERROR", "Idempotency-Key должен быть UUID v4")
    lock = int.from_bytes(hashlib.sha256(f"{user.id}:{operation}:{key}".encode()).digest()[:8], signed=True)
    await db.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})
    existing = await db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user.id,
            IdempotencyKey.operation == operation,
            IdempotencyKey.idempotency_key == key,
        )
    )
    digest = hashlib.sha256(
        json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if existing and existing.expires_at <= datetime.now(UTC):
        await db.delete(existing)
        await db.flush()
        existing = None
    if existing and existing.request_hash != digest:
        raise ApiError(409, "IDEMPOTENCY_CONFLICT", "Ключ уже использован с другими данными")
    return existing, digest


def remember(db, user, key, operation, digest, response, *, status_code=201):
    db.add(
        IdempotencyKey(
            user_id=user.id,
            operation=operation,
            idempotency_key=key,
            request_hash=digest,
            response_status=status_code,
            response_body=jsonable_encoder(response),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
    )
