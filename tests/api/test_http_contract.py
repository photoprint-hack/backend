import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def public_client():
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield client


async def test_no_auth_has_unified_error(public_client):
    response = await public_client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_TOKEN_EXPIRED"
    assert response.json()["detail"]["request_id"] == response.headers["x-request-id"]
    assert response.headers["www-authenticate"] == "Bearer"


async def test_validation_does_not_echo_password(public_client):
    secret = "secret-value-to-not-leak"
    response = await public_client.post(
        "/api/v1/auth/login", json={"email": "invalid", "password": secret, "extra": "field"}
    )
    assert response.status_code == 422
    assert secret not in response.text
    assert response.json()["detail"]["fields"]


async def test_foreign_origin_is_denied_without_database_access(public_client):
    response = await public_client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://foreign.example"},
        json={"email": "a@example.com", "password": "Password123!"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ORIGIN_NOT_ALLOWED"


async def test_refresh_without_cookie_clears_cookie(public_client):
    response = await public_client.post("/api/v1/auth/refresh")
    assert response.status_code == 401
    assert "refresh_token=" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


async def test_openapi_bearer_and_responses(public_client):
    response = await public_client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert "/api/v1/auth/login" in schema["paths"]
    assert "201" in schema["paths"]["/api/v1/users"]["post"]["responses"]
    assert "/api/v1/health" not in schema["paths"]
