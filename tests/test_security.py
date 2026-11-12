from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.exceptions import ApiError
from app.core.permissions import department_scope
from app.core.security import decode_token, hash_password, issue_token, token_digest, verify_password
from app.models import User
from app.schemas.identity import UserCreate, UserPatch
from app.services.audit import safe_values


def test_password_hash_is_argon2id_and_verifies():
    hashed = hash_password("TestingPassword123!")
    assert hashed.startswith("$argon2id$")
    assert verify_password("TestingPassword123!", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("wrong", "corrupt-hash")


def test_access_refresh_are_not_interchangeable():
    uid = uuid4()
    sid = uuid4()
    access, _ = issue_token(uid, "access")
    refresh, _ = issue_token(uid, "refresh", session_id=sid)
    assert decode_token(access, "access")["sub"] == str(uid)
    assert decode_token(refresh, "refresh")["sid"] == str(sid)
    with pytest.raises(ApiError):
        decode_token(refresh, "access")
    with pytest.raises(ApiError):
        decode_token(access, "refresh")
    assert token_digest(refresh) != refresh


def test_expired_and_unsigned_tokens_rejected():
    config = get_settings()
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "jti": str(uuid4()),
            "type": "access",
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "iss": "photoprint",
            "aud": "photoprint-api",
        },
        config.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(ApiError):
        decode_token(token, "access")
    with pytest.raises(ApiError):
        decode_token("invalid", "access")


def test_production_requires_secure_origins_and_cookie():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", jwt_secret_key="x" * 40)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret_key="short")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret_key="x" * 40, cookie_samesite="none", cookie_secure=False)


def test_postgresql_connection_normalization_does_not_log_secrets():
    config = Settings(
        _env_file=None,
        jwt_secret_key="x" * 40,
        database_url="postgresql://test:private@localhost/db?sslmode=require",
    )
    assert config.db_url() == "postgresql+asyncpg://test:private@localhost/db?ssl=require"
    assert "private" not in repr(config)


def test_department_scope_cannot_be_overridden():
    own = uuid4()
    other = uuid4()
    manager = User(id=uuid4(), role="manager", department_id=own)
    assert department_scope(manager) == own
    assert department_scope(manager, own) == own
    with pytest.raises(ApiError) as exc:
        department_scope(manager, other)
    assert exc.value.status == 403


def test_user_validation_and_password_exclusion():
    with pytest.raises(ValidationError):
        UserCreate(
            email="m@example.com", full_name="Manager", role="manager", temporary_password="LongPassword123!"
        )
    with pytest.raises(ValidationError):
        UserPatch()
    with pytest.raises(ValidationError):
        UserPatch(role=None)
    payload = UserCreate(
        email="ADMIN@EXAMPLE.COM", full_name="Admin", role="admin", temporary_password="LongPassword123!"
    )
    assert payload.email == "admin@example.com"


def test_audit_recursively_redacts_secrets():
    result = safe_values(
        {
            "password_hash": "hidden",
            "nested": {"refresh_token": "hidden", "jwt_secret_key": "hidden", "status": "new"},
            "values": [{"Authorization": "hidden"}],
        }
    )
    assert result["password_hash"] == "[REDACTED]"
    assert result["nested"]["status"] == "new"
    assert "hidden" not in str(result)


@pytest.mark.parametrize(
    ("actual", "target", "direction", "expected"),
    [
        ("95", "100", "higher_is_better", "normal"),
        ("90", "100", "higher_is_better", "warning"),
        ("89.999", "100", "higher_is_better", "critical"),
        ("105", "100", "lower_is_better", "normal"),
        ("110", "100", "lower_is_better", "warning"),
        ("110.001", "100", "lower_is_better", "critical"),
        ("69.99", "100", "range", "warning"),
        ("70", "100", "range", "normal"),
        ("100", "100", "range", "normal"),
        ("100.001", "100", "range", "warning"),
        ("110", "100", "range", "warning"),
        ("110.001", "100", "range", "critical"),
        ("0", "0", "higher_is_better", "normal"),
        ("1", "0", "higher_is_better", "no_data"),
    ],
)
def test_business_threshold_boundaries(actual, target, direction, expected):
    from decimal import Decimal

    from app.services.analytics import classify

    assert classify(Decimal(actual), Decimal(target), direction)[0] == expected
