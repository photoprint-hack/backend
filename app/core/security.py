import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import get_settings
from app.core.exceptions import ApiError

password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("dummy-password-never-used-for-login")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hash.verify(password, hashed)
    except (ValueError, UnknownHashError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(
    user_id: UUID, kind: str, *, session_id: UUID | None = None, jti: UUID | None = None
) -> tuple[str, dict]:
    config = get_settings()
    now = datetime.now(UTC)
    expires = now + (
        timedelta(minutes=config.access_token_expire_minutes)
        if kind == "access"
        else timedelta(days=config.refresh_token_expire_days)
    )
    claims = {
        "sub": str(user_id),
        "type": kind,
        "jti": str(jti or uuid4()),
        "iat": now,
        "exp": expires,
        "iss": "photoprint",
        "aud": "photoprint-api",
    }
    if session_id:
        claims["sid"] = str(session_id)
    return jwt.encode(
        claims, config.jwt_secret_key.get_secret_value(), algorithm=config.jwt_algorithm
    ), claims


def decode_token(token: str, kind: str) -> dict:
    config = get_settings()
    try:
        claims = jwt.decode(
            token,
            config.jwt_secret_key.get_secret_value(),
            algorithms=[config.jwt_algorithm],
            issuer="photoprint",
            audience="photoprint-api",
            options={"require": ["sub", "jti", "iat", "exp", "type"]},
        )
        UUID(claims["sub"])
        UUID(claims["jti"])
        if claims["type"] != kind:
            raise ValueError("Wrong token type")
        if kind == "refresh":
            UUID(claims["sid"])
        return claims
    except (jwt.InvalidTokenError, ValueError, KeyError, TypeError) as exc:
        raise ApiError(
            401,
            "AUTH_REFRESH_INVALID" if kind == "refresh" else "AUTH_TOKEN_EXPIRED",
            "Сессия недействительна",
            clear_refresh=kind == "refresh",
        ) from exc
