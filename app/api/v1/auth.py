from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import DB, CurrentUser, check_origin
from app.core.config import get_settings
from app.schemas.common import Data
from app.schemas.identity import Login, LoginResult, Success, Tokens, UserOut
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


def refresh_cookie(response: Response, raw: str):
    config = get_settings()
    response.set_cookie(
        "refresh_token",
        raw,
        max_age=config.refresh_token_expire_days * 86400,
        path="/api/v1/auth",
        secure=config.cookie_secure,
        httponly=True,
        samesite=config.cookie_samesite,
    )
    response.headers["Cache-Control"] = "no-store"


@router.post("/login", response_model=Data[LoginResult], dependencies=[Depends(check_origin)])
async def login(payload: Login, request: Request, response: Response, db: DB):
    user = await auth.credentials(db, str(payload.email), payload.password, request)
    access, refresh = await auth.login(db, user, request)
    refresh_cookie(response, refresh)
    return {
        "data": {
            "access_token": access,
            "user": UserOut.model_validate(user),
            "token_type": "bearer",
            "expires_in": 900,
        }
    }


@router.post("/refresh", response_model=Data[Tokens], dependencies=[Depends(check_origin)])
async def refresh(request: Request, response: Response, db: DB):
    access, raw = await auth.refresh(db, request.cookies.get("refresh_token"), request)
    refresh_cookie(response, raw)
    return {"data": {"access_token": access, "token_type": "bearer", "expires_in": 900}}


@router.post("/logout", response_model=Data[Success], dependencies=[Depends(check_origin)])
async def logout(request: Request, response: Response, db: DB, user: CurrentUser):
    await auth.logout(db, user, request.cookies.get("refresh_token"), request)
    config = get_settings()
    response.delete_cookie(
        "refresh_token",
        path="/api/v1/auth",
        secure=config.cookie_secure,
        httponly=True,
        samesite=config.cookie_samesite,
    )
    response.headers["Cache-Control"] = "no-store"
    return {"data": {"success": True}}


@router.get("/me", response_model=Data[UserOut])
async def me(user: CurrentUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"data": user}
