from datetime import UTC, datetime
from uuid import uuid4

import jwt

from app.core.config import get_settings


async def test_required_summaries_and_forecast(client, database, seeded):
    for endpoint in [
        "/sales/summary",
        "/sales/funnel",
        "/production/summary",
        "/finance/summary",
        "/hr/summary",
        "/forecast",
        "/data-quality/overview",
        "/data-quality/reconciliation",
    ]:
        response = await client.get("/api/v1" + endpoint, headers=seeded)
        assert response.status_code == 200, (endpoint, response.text)
    sales = (await client.get("/api/v1/sales/summary", headers=seeded)).json()["data"]
    assert sales["orders_count"] > 0
    assert sales["conversion_percent"] > 0
    finance = (await client.get("/api/v1/finance/summary", headers=seeded)).json()["data"]
    assert finance["revenue"] == finance["gross_profit"] + finance["direct_cost"]
    assert set(finance["bdds"]) == {"inflow", "outflow", "net"}
    forecast = (await client.get("/api/v1/forecast", headers=seeded)).json()["data"]
    assert forecast["status"] == "ready"
    assert forecast["horizon_weeks"] == 4
    assert len(forecast["items"]) == 4
    assert forecast["unit"] == "standard_hour"
    assert forecast["first_deficit_week"]
    for item in forecast["items"]:
        assert abs(item["deficit"] - max(item["demand"] - item["available_capacity"], 0)) < 0.001
        assert abs(item["reserve"] - max(item["available_capacity"] - item["demand"], 0)) < 0.001
    reconciliation = (await client.get("/api/v1/data-quality/reconciliation", headers=seeded)).json()["data"]
    assert reconciliation["difference"] == 0
    assert reconciliation["status"] == "normal"
    history = await client.get("/api/v1/metrics/revenue/history?interval=week", headers=seeded)
    assert history.status_code == 200, history.text
    assert history.json()["items"]


async def test_bi_signed_manager_scope_and_fail_closed(client, database, seeded, monkeypatch):
    unavailable = await client.get("/api/v1/analytics/metabase-embed", headers=seeded)
    assert unavailable.status_code == 503
    config = get_settings()
    monkeypatch.setattr(config, "metabase_url", "https://bi.example.test")
    from pydantic import SecretStr

    monkeypatch.setattr(
        config, "metabase_embedding_secret", SecretStr("a-separate-bi-signing-key-at-least-32-bytes")
    )
    monkeypatch.setattr(config, "metabase_dashboard_ids", {"company": 5})
    monkeypatch.setattr(config, "metabase_verified_dashboards", ["company"])
    manager = await client.post(
        "/api/v1/auth/login", json={"email": "manager@fotoprint.demo", "password": "SeedPassword123!"}
    )
    headers = {"Authorization": "Bearer " + manager.json()["data"]["access_token"]}
    response = await client.get("/api/v1/analytics/metabase-embed", headers=headers)
    assert response.status_code == 200, response.text
    url = response.json()["data"]["embed_url"]
    token = url.split("/embed/dashboard/")[1].split("#")[0]
    claims = jwt.decode(token, config.metabase_embedding_secret.get_secret_value(), algorithms=["HS256"])
    assert claims["resource"]["dashboard"] == 5
    assert claims["params"]["department_id"] == manager.json()["data"]["user"]["department_id"]
    assert claims["exp"] - datetime.now(UTC).timestamp() <= 300
    denied = await client.get(
        "/api/v1/analytics/metabase-embed?department_id=" + str(uuid4()), headers=headers
    )
    assert denied.status_code == 403
    audit = await client.get("/api/v1/audit-logs", headers=headers)
    assert audit.status_code == 403
