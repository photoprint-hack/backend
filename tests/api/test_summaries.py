from datetime import date, timedelta

import pytest


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


@pytest.mark.parametrize(
    ("days", "interval", "expected_status"),
    [
        (31, "day", 200),
        (32, "day", 422),
        (33, "day", 422),
        (31, None, 200),
        (32, None, 422),
        (366, "week", 200),
        (366, "month", 200),
        (367, "week", 422),
        (367, "month", 422),
    ],
)
async def test_metric_history_period_limits(client, minimal_admin, days, interval, expected_status):
    start = date(2025, 1, 1)
    params = {
        "date_from": start.isoformat(),
        "date_to": (start + timedelta(days=days - 1)).isoformat(),
        "page_size": 100,
    }
    if interval is not None:
        params["interval"] = interval
    response = await client.get("/api/v1/metrics/revenue/history", headers=minimal_admin, params=params)
    assert response.status_code == expected_status, response.text
    body = response.json()
    if expected_status == 200:
        assert body["metric_code"] == "revenue"
        assert body["items"][0]["period_start"] == params["date_from"]
        assert body["items"][-1]["period_end"] == params["date_to"]
        if interval in {None, "day"}:
            assert body["total"] == days
    else:
        assert body["detail"]["code"] == "VALIDATION_ERROR"
