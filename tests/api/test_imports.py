from datetime import UTC, datetime

from sqlalchemy import func, select

from app.models import Customer, SourceRecord


async def test_partial_import_replay_and_quality(client, database, minimal_admin):
    stamp = datetime.now(UTC).isoformat()
    good = {
        "entity_type": "customer",
        "external_id": "customer-1",
        "event_at": stamp,
        "data": {
            "name": "Synthetic client",
            "customer_type": "b2c",
            "segment": "retail",
            "acquisition_channel": "website",
        },
    }
    bad = {
        "entity_type": "customer",
        "external_id": "customer-2",
        "event_at": stamp,
        "data": {"customer_type": "b2c", "segment": "retail", "acquisition_channel": "website"},
    }
    response = await client.post(
        "/api/v1/integrations/crm/import", headers=minimal_admin, json={"records": [good, bad, good]}
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["status"] == "partial_success"
    assert result["inserted"] == 1
    assert result["failed"] == 2
    assert {x["code"] for x in result["errors"]} == {"missing_fields", "duplicates"}
    replay = await client.post(
        "/api/v1/integrations/crm/import", headers=minimal_admin, json={"records": [good]}
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["skipped"] == 1
    updated = await client.post(
        "/api/v1/integrations/crm/import",
        headers=minimal_admin,
        json={"records": [{**good, "data": {**good["data"], "name": "Updated client"}}]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["updated"] == 1
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Customer)) == 1
        assert (await db.scalar(select(Customer))).name == "Updated client"
    history = await client.get("/api/v1/integrations/history", headers=minimal_admin)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 3
    sources = await client.get("/api/v1/data-quality/sources", headers=minimal_admin)
    assert sources.status_code == 200
    crm = next(x for x in sources.json()["items"] if x["code"] == "crm")
    assert crm["records_count"] == 1
    check = await client.post("/api/v1/data-quality/check", headers=minimal_admin, json={})
    assert check.status_code == 200, check.text
    issues = await client.get("/api/v1/data-quality/issues", headers=minimal_admin)
    assert issues.status_code == 200
    assert issues.json()["total"] >= 4


async def test_bad_foreign_link_does_not_damage_existing_data(client, database, minimal_admin):
    stamp = datetime.now(UTC).isoformat()
    response = await client.post(
        "/api/v1/integrations/finance/import",
        headers=minimal_admin,
        json={
            "records": [
                {
                    "entity_type": "finance_record",
                    "external_id": "f-1",
                    "event_at": stamp,
                    "data": {
                        "department_id": {
                            "source": "erp",
                            "entity_type": "department",
                            "external_id": "missing",
                        },
                        "record_date": "2026-11-01",
                        "record_type": "revenue",
                        "amount": 100,
                        "currency": "BYN",
                    },
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["failed"] == 1
    assert response.json()["data"]["errors"][0]["code"] == "broken_relations"
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(SourceRecord)) == 0


async def test_won_deal_import_requires_matching_order(client, database, seeded, minimal_admin):
    from app.models import Order

    async with database() as db:
        order = await db.scalar(select(Order))
    record = {
        "entity_type": "deal",
        "external_id": "invalid-won-deal",
        "event_at": datetime.now(UTC).isoformat(),
        "data": {
            "customer_id": str(order.customer_id),
            "department_id": str(order.department_id),
            "product_id": str(order.product_id),
            "channel": "website",
            "segment": "retail",
            "stage": "won",
            "expected_amount": 100,
            "currency": "BYN",
        },
    }
    response = await client.post(
        "/api/v1/integrations/crm/import", headers=minimal_admin, json={"records": [record]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["failed"] == 1
    assert response.json()["data"]["errors"][0]["code"] == "broken_relations"
