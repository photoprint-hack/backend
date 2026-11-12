import hmac
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import ApiError
from app.core.security import DUMMY_HASH, decode_token, issue_token, token_digest, verify_password
from app.models import RefreshToken, User
from app.services.audit import record


async def credentials(db: AsyncSession, email: str, password: str, request: Request) -> User:
    user = await db.scalar(select(User).where(User.email == email).with_for_update())
    valid = await run_in_threadpool(verify_password, password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid or not user.is_active:
        record(db, "auth.login", "user", actor=user, status="failure", request=request)
        await db.commit()
        raise ApiError(401, "AUTH_INVALID_CREDENTIALS", "Неверная почта или пароль")
    return user


def new_pair(db: AsyncSession, user: User, session_id: UUID) -> tuple[str, str, RefreshToken]:
    refresh, claims = issue_token(user.id, "refresh", session_id=session_id)
    token = RefreshToken(
        id=UUID(claims["jti"]),
        jti=UUID(claims["jti"]),
        user_id=user.id,
        session_id=session_id,
        token_hash=token_digest(refresh),
        expires_at=claims["exp"],
    )
    db.add(token)
    access, _ = issue_token(user.id, "access")
    return access, refresh, token


async def login(db: AsyncSession, user: User, request: Request):
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    access, refresh, _ = new_pair(db, user, uuid4())
    record(db, "auth.login", "user", actor=user, object_id=user.id, request=request)
    await db.commit()
    return access, refresh


async def refresh(db: AsyncSession, raw: str | None, request: Request):
    if not raw:
        raise ApiError(401, "AUTH_REFRESH_INVALID", "Сессия недействительна", clear_refresh=True)
    claims = decode_token(raw, "refresh")
    user = await db.scalar(select(User).where(User.id == UUID(claims["sub"])).with_for_update())
    token = await db.scalar(
        select(RefreshToken).where(RefreshToken.jti == UUID(claims["jti"])).with_for_update()
    )
    if (
        not user
        or not user.is_active
        or not token
        or token.user_id != user.id
        or str(token.session_id) != claims["sid"]
        or not hmac.compare_digest(token.token_hash, token_digest(raw))
    ):
        raise ApiError(401, "AUTH_REFRESH_INVALID", "Сессия недействительна", clear_refresh=True)
    if token.revoked_at is not None:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.session_id == token.session_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        record(
            db,
            "auth.refresh",
            "user",
            actor=user,
            status="failure",
            details={"reason": "revoked_refresh_reuse"},
            request=request,
        )
        await db.commit()  # Revocation must survive the subsequent 401.
        raise ApiError(401, "AUTH_REFRESH_INVALID", "Сессия отозвана", clear_refresh=True)
    if token.expires_at <= datetime.now(UTC):
        raise ApiError(401, "AUTH_REFRESH_INVALID", "Сессия истекла", clear_refresh=True)
    access, new_refresh, replacement = new_pair(db, user, token.session_id)
    await db.flush()
    token.revoked_at = datetime.now(UTC)
    token.replaced_by_id = replacement.id
    record(db, "auth.refresh", "user", actor=user, object_id=user.id, request=request)
    await db.commit()
    return access, new_refresh


async def logout(db: AsyncSession, user: User, raw: str | None, request: Request):
    await db.scalar(select(User).where(User.id == user.id).with_for_update())
    if raw:
        # Match the stored digest as well as ownership; invalid cookies cannot revoke another user.
        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user.id,
                RefreshToken.token_hash == token_digest(raw),
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
    record(db, "auth.logout", "user", actor=user, object_id=user.id, request=request)
    await db.commit()
