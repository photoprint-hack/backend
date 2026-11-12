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
