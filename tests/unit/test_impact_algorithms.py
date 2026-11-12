import json
import urllib.error

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings, get_settings
from app.core.exceptions import ApiError
from app.services.impact import graph, provider


def test_bfs_cycles_directions_filters_and_no_hidden_bridge():
    full = {
        "nodes": [{"id": x} for x in "abc"],
        "edges": [
            {"source": "a", "target": "b", "type": "feeds"},
            {"source": "b", "target": "c", "type": "depends_on"},
            {"source": "c", "target": "a", "type": "feeds"},
        ],
    }
    assert len(graph.explore(full, "a", 1, "out")["nodes"]) == 2
    assert len(graph.explore(full, "a", 3, "both")["nodes"]) == 3
    assert len(graph.explore(full, "a", 3, "out", ["feeds"])["nodes"]) == 2
    path = graph.explore(full, "a", 3, "out", target="c")
    assert [e["target"] for e in path["edges"]] == ["b", "c"]
    permitted = {"nodes": [{"id": "a"}, {"id": "c"}], "edges": []}
    assert graph.explore(permitted, "a", 3, "out", target="c")["nodes"] == []
    with pytest.raises(ApiError) as error:
        graph.explore(permitted, "b")
    assert error.value.status == 404


def test_openrouter_request_enforces_free_structured_contract(monkeypatch):
    config = get_settings()
    monkeypatch.setattr(config, "openrouter_api_key", SecretStr("test-key"))
    value = dict(
        summary="Проверка",
        changes=[],
        verified_facts=[],
        calculated_dependencies=[],
        correlations=[],
        hypotheses=[],
        possible_impacts=[],
        recommendations=[],
        data_gaps=[],
        suggested_responsible=None,
        draft_text="Черновик",
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return json.dumps(
                {"model": "actual/free", "choices": [{"message": {"content": json.dumps(value)}}]}
            ).encode()

    def transport(request, timeout):
        assert request.full_url == "https://openrouter.ai/api/v1/chat/completions"
        body = json.loads(request.data)
        assert body["model"] == "openrouter/free"
        assert body["provider"] == {"require_parameters": True, "max_price": {"prompt": 0, "completion": 0}}
        assert body["response_format"]["json_schema"]["strict"] is True
        assert "tools" not in body and "models" not in body
        return Response()

    monkeypatch.setattr(provider.urllib.request, "urlopen", transport)
    content, model = provider._request({"synthetic_demo": True})
    assert content == value and model == "actual/free"
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            jwt_secret_key="test-key-which-is-at-least-thirty-two-bytes",
            openrouter_model="paid/model",
        )


@pytest.mark.parametrize("code,expected", [(429, "AI_RATE_LIMITED"), (500, "AI_UNAVAILABLE")])
def test_provider_errors_never_return_upstream_secrets(monkeypatch, code, expected):
    monkeypatch.setattr(get_settings(), "openrouter_api_key", SecretStr("test-key"))

    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.invalid", code, "PRIVATE_PROVIDER_BODY", {}, None)

    monkeypatch.setattr(provider.urllib.request, "urlopen", fail)
    with pytest.raises(ApiError) as error:
        provider._request({"synthetic_demo": True})
    assert error.value.code == expected and "PRIVATE" not in error.value.message
