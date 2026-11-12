from uuid import UUID

from sqlalchemy import func, select

from app.models import Customer, SourceSyncRun
from app.services.imports import REGISTRY


async def test_mock_sources_read_database_paginate_and_do_not_write(client, database, seeded):
    login = await client.post(
        "/api/v1/auth/login", json={"email": "admin@fotoprint.demo", "password": "SeedPassword123!"}
    )
    headers = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
    async with database() as db:
        before = {
            source: {
                name: await db.scalar(select(func.count()).select_from(model))
                for name, model in entities.items()
            }
            for source, entities in REGISTRY.items()
        }
        runs_before = await db.scalar(select(func.count()).select_from(SourceSyncRun))
    for source in REGISTRY:
        response = await client.get(
            f"/api/v1/mock-sources/{source}/records", headers=headers, params={"page_size": 7}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == sum(before[source].values())
        assert 0 < len(body["items"]) <= 7
        for row in body["items"]:
            assert set(row) == {"entity_type", "external_id", "event_at", "data"}
            assert row["entity_type"] in REGISTRY[source]
            assert row["event_at"] and row["external_id"]
            assert (
                not {"password_hash", "refresh_token", "actor_id", "id", "updated_at", "version"}
                & row["data"].keys()
            )
        repeat = await client.get(
            f"/api/v1/mock-sources/{source}/records", headers=headers, params={"page_size": 7}
        )
        assert repeat.json() == body
        next_page = await client.get(
            f"/api/v1/mock-sources/{source}/records", headers=headers, params={"page_size": 7, "page": 2}
        )

        def keys(result):
            return {(x["entity_type"], x["external_id"]) for x in result["items"]}

        assert not keys(body) & keys(next_page.json())
        assert (await client.get(f"/api/v1/mock-sources/{source}/records", headers=seeded)).status_code == 403
    async with database() as db:
        after = {
            source: {
                name: await db.scalar(select(func.count()).select_from(model))
                for name, model in entities.items()
            }
            for source, entities in REGISTRY.items()
        }
        assert before == after
        assert await db.scalar(select(func.count()).select_from(SourceSyncRun)) == runs_before
        customer = await db.scalar(select(Customer).order_by(Customer.id))
        customer.name = "Updated database CRM name"
        await db.commit()
        customer_id, external_id = customer.id, customer.external_id
    # Customer is the first CRM entity group; page size one gives the exact first row.
    response = await client.get("/api/v1/mock-sources/crm/records?page_size=1", headers=headers)
    row = response.json()["items"][0]
    assert row["entity_type"] == "customer"
    assert row["data"]["name"] == "Updated database CRM name"
    assert row["external_id"] == external_id or UUID(row["external_id"]) == customer_id
    assert (await client.get("/api/v1/mock-sources/unknown/records", headers=headers)).status_code == 422
    assert (
        await client.get("/api/v1/mock-sources/crm/records?page_size=101", headers=headers)
    ).status_code == 422
    assert (await client.get("/api/v1/mock-sources/crm/records")).status_code == 401
    empty = await client.get("/api/v1/mock-sources/crm/records?page=999999", headers=headers)
    assert empty.status_code == 200 and empty.json()["items"] == []
    for role in ["manager", "analyst", "employee"]:
        session = await client.post(
            "/api/v1/auth/login", json={"email": role + "@fotoprint.demo", "password": "SeedPassword123!"}
        )
        role_headers = {"Authorization": "Bearer " + session.json()["data"]["access_token"]}
        assert (await client.get("/api/v1/mock-sources/crm/records", headers=role_headers)).status_code == 403
