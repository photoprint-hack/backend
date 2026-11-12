import json
import logging
from io import StringIO
from uuid import uuid4

import pytest
from starlette.requests import Request

from app.core.exceptions import ApiError, handle_api_error
from app.core.logging import SafeJsonFormatter
from app.models import User


@pytest.mark.parametrize("status", [403, 409, 422])
async def test_failed_audit_commit_logs_request_id_and_preserves_error_without_secrets(status):
    private = "postgresql://user:private-password@db.invalid/database bearer private-token"
    actor = User(id=uuid4(), full_name="Test actor")

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args):
            return actor

        def add(self, obj):
            pass

        async def commit(self):
            raise RuntimeError(private)

    request = Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": "/api/v1/tasks/" + str(uuid4()),
            "headers": [(b"authorization", b"Bearer private-token"), (b"cookie", b"private-cookie")],
        }
    )
    request.state.request_id = uuid4()
    request.state.actor_id = actor.id
    request.state.session_factory = Session
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(SafeJsonFormatter())
    logger = logging.getLogger("photoprint.audit")
    logger.addHandler(handler)
    try:
        response = await handle_api_error(request, ApiError(status, "EXPECTED_FAILURE", "Original refusal"))
    finally:
        logger.removeHandler(handler)
    assert response.status_code == status
    body = json.loads(response.body)
    assert body["detail"]["code"] == "EXPECTED_FAILURE"
    assert body["detail"]["message"] == "Original refusal"
    event = json.loads(stream.getvalue())
    assert event["request_id"] == str(request.state.request_id)
    assert event["status_code"] == status
    assert event["level"] == "ERROR"
    for secret in ["private-password", "private-token", "private-cookie", "postgresql://"]:
        assert secret not in response.body.decode() + stream.getvalue()
