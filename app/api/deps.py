from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import decode_token
from app.db.session import get_db
from app.models import User

bearer = HTTPBearer(auto_error=False)
DB = Annotated[AsyncSession, Depends(get_db)]


async def current_user(
    request: Request, db: DB, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> User:
    if credentials is None:
        raise ApiError(401, "AUTH_TOKEN_EXPIRED", "Необходима авторизация")
    claims = decode_token(credentials.credentials, "access")
    user = await db.get(User, UUID(claims["sub"]))
    if not user or not user.is_active:
        raise ApiError(401, "AUTH_TOKEN_EXPIRED", "Пользователь недоступен")
    request.state.actor_id = user.id
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def check_origin(request: Request):
    config = get_settings()
    origin = request.headers.get("origin")
    if (
        origin is not None
        and origin != config.frontend_url
        or origin is None
        and config.app_env == "production"
    ):
        raise ApiError(403, "ORIGIN_NOT_ALLOWED", "Недопустимый источник запроса")
