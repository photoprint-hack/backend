from datetime import date
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    app_env: Literal["development", "testing", "production"] = "development"
    app_name: str = "photoprint"
    app_version: str = "1.2.0"
    database_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/photoprint")
    migration_database_url: SecretStr | None = None
    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    report_timezone: str = "Europe/Minsk"
    port: int = 8000
    demo_mode: bool = False
    demo_reference_date: str | None = None
    metabase_url: str | None = None
    metabase_embedding_secret: SecretStr | None = None
    metabase_dashboard_ids: dict[str, int] = {}
    metabase_verified_dashboards: list[str] = []
    ai_provider: Literal["openrouter"] = "openrouter"
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = "openrouter/free"
    ai_timeout_seconds: int = 30
    ai_cache_ttl_seconds: int = 900
    ai_daily_budget: int = 40
    business_holidays: list[date] = []
    worker_poll_seconds: int = 10

    @field_validator("openrouter_model")
    @classmethod
    def free_model_only(cls, value: str) -> str:
        if value != "openrouter/free" and not value.endswith(":free"):
            raise ValueError("Only explicitly free OpenRouter models are allowed")
        return value

    @field_validator("ai_timeout_seconds", "ai_cache_ttl_seconds", "ai_daily_budget", "worker_poll_seconds")
    @classmethod
    def positive_limit(cls, value: int) -> int:
        if not 1 <= value <= 86400:
            raise ValueError("Expected a positive bounded limit")
        return value

    test_database_url: SecretStr | None = None

    demo_admin_password: SecretStr | None = None
    demo_director_password: SecretStr | None = None
    demo_manager_password: SecretStr | None = None
    demo_analyst_password: SecretStr | None = None
    demo_employee_password: SecretStr | None = None

    @field_validator("jwt_secret_key")
    @classmethod
    def strong_key(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode()) < 32:
            raise ValueError("JWT_SECRET_KEY must contain at least 32 bytes")
        return value

    @field_validator("frontend_url", "backend_url")
    @classmethod
    def origin(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.netloc
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise ValueError("Expected an exact HTTP(S) origin")
        return value.rstrip("/")

    @field_validator("report_timezone")
    @classmethod
    def timezone_exists(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @model_validator(mode="after")
    def production_security(self) -> "Settings":
        if self.access_token_expire_minutes != 15 or self.refresh_token_expire_days != 7:
            raise ValueError("The API contract requires 15-minute access and 7-day refresh tokens")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("SameSite=none requires Secure cookies")
        if self.app_env == "production":
            if (
                not self.cookie_secure
                or not self.frontend_url.startswith("https://")
                or not self.backend_url.startswith("https://")
            ):
                raise ValueError("Production requires HTTPS origins and Secure cookies")
        return self

    def db_url(self, *, migrations: bool = False) -> str:
        secret = (
            self.migration_database_url if migrations and self.migration_database_url else self.database_url
        )
        url = make_url(secret.get_secret_value())
        if url.get_backend_name() not in {"postgres", "postgresql"}:
            raise ValueError("PostgreSQL is required")
        query = dict(url.query)
        if "sslmode" in query:
            query["ssl"] = query.pop("sslmode")
        query.pop("channel_binding", None)  # libpq-only parameter, not an asyncpg keyword
        return url.set(drivername="postgresql+asyncpg", query=query).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
