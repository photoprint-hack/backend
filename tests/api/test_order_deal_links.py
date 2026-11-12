from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models import Customer, Deal, Department, Order, OrderEvent, Product, SourceRecord


@pytest.fixture
async def links(database, minimal_admin):
    async with database() as db:
        departments = [Department(code=f"links-{i}", name=f"Department {i}") for i in range(2)]
        customers = [
            Customer(name=f"Customer {i}", customer_type="b2b", segment="test", acquisition_channel="web")
            for i in range(2)
        ]
        products = [
            Product(
                code=f"links-{i}",
                name=f"Product {i}",
                category="test",
                standard_price=10,
                standard_hours_per_unit=1,
                is_active=True,
            )
            for i in range(2)
        ]
        db.add_all([*departments, *customers, *products])
        await db.flush()

        def order(number):
            return Order(
                order_number=number,
                customer_id=customers[0].id,
                department_id=departments[0].id,
                product_id=products[0].id,
                quantity=1,
                standard_hours_per_unit=1,
                amount=10,
                channel="web",
                due_at=datetime.now(UTC) + timedelta(days=2),
            )

        free_order, occupied_order, reverse_order = [order(n) for n in ["FREE", "OCCUPIED", "REVERSE"]]
        db.add_all([free_order, occupied_order, reverse_order])
        await db.flush()

        def deal(product, order_id=None):
            return Deal(
                customer_id=customers[0].id,
                department_id=departments[0].id,
                product_id=product,
                channel="web",
                segment="test",
                stage="qualified",
                expected_amount=10,
                order_id=order_id,
            )

        free_deal = deal(products[0].id)
        no_product = deal(None)
        occupied = deal(products[0].id, occupied_order.id)
        reverse = deal(products[0].id)
        db.add_all([free_deal, no_product, occupied, reverse])
        await db.flush()
        reverse_order.crm_deal_id = reverse.id
        await db.commit()
        return SimpleNamespace(
            departments=departments,
            customers=customers,
            products=products,
            free_order=free_order,
            occupied_order=occupied_order,
            reverse_order=reverse_order,
            free_deal=free_deal,
            no_product=no_product,
            occupied=occupied,
            reverse=reverse,
        )


def order_data(links):
    return {
        "customer_id": str(links.customers[0].id),
        "department_id": str(links.departments[0].id),
        "product_id": str(links.products[0].id),
        "quantity": 1,
        "amount": 10,
        "channel": "web",
        "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "crm_deal_id": str(links.free_deal.id),
    }


def deal_data(links):
    return {
        "customer_id": str(links.customers[0].id),
        "department_id": str(links.departments[0].id),
        "product_id": str(links.products[0].id),
        "channel": "web",
        "segment": "test",
        "stage": "qualified",
        "expected_amount": 10,
        "order_id": str(links.free_order.id),
    }


def mismatch(data, links, case, *, is_order):
    if case in {"customer", "department", "product"}:
        collection = getattr(
            links, {"customer": "customers", "department": "departments", "product": "products"}[case]
        )
        data[case + "_id"] = str(collection[1].id)
    elif is_order:
        data["crm_deal_id"] = str(getattr(links, case).id)
    else:
        data["order_id"] = str(getattr(links, case + "_order" if case == "occupied" else "reverse_order").id)
    return data


def record(entity, data, external="LINK-IMPORT"):
    return {
        "entity_type": entity,
        "external_id": external,
        "event_at": datetime.now(UTC).isoformat(),
        "data": data,
    }


@pytest.mark.parametrize("case", ["customer", "department", "product", "occupied", "reverse"])
async def test_api_rejects_mismatched_or_occupied_deal(client, database, minimal_admin, links, case):
    payload = mismatch(order_data(links), links, case, is_order=True)
    response = await client.post(
        "/api/v1/orders", headers={**minimal_admin, "Idempotency-Key": str(uuid4())}, json=payload
    )
    assert response.status_code == 422, response.text
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Order)) == 3
        assert await db.scalar(select(func.count()).select_from(OrderEvent)) == 0
        assert (await db.get(Deal, links.free_deal.id)).order_id is None


@pytest.mark.parametrize("without_product", [False, True])
async def test_api_accepts_matching_and_unspecified_deal_product(
    client, database, minimal_admin, links, without_product
):
    payload = order_data(links)
    if without_product:
        payload["crm_deal_id"] = str(links.no_product.id)
    response = await client.post(
        "/api/v1/orders", headers={**minimal_admin, "Idempotency-Key": str(uuid4())}, json=payload
    )
    assert response.status_code == 201, response.text
    async with database() as db:
        from uuid import UUID

        deal = await db.get(Deal, UUID(payload["crm_deal_id"]))
        assert str(deal.order_id) == response.json()["data"]["id"]


@pytest.mark.parametrize("entity", ["order", "deal"])
@pytest.mark.parametrize("case", ["customer", "department", "product", "occupied", "reverse"])
async def test_import_keeps_good_record_and_rejects_bad_link(
    client, database, minimal_admin, links, entity, case
):
    data = order_data(links) if entity == "order" else deal_data(links)
    if entity == "order":
        data.update(order_number="INVALID-LINK", standard_hours_per_unit=1)
    mismatch(data, links, case, is_order=entity == "order")
    good = order_data(links) if entity == "order" else deal_data(links)
    if entity == "order":
        good.update(order_number="VALID-LINK", standard_hours_per_unit=1)
    source = "erp" if entity == "order" else "crm"
    response = await client.post(
        f"/api/v1/integrations/{source}/import",
        headers=minimal_admin,
        json={"records": [record(entity, data, "BAD-LINK"), record(entity, good, "GOOD-LINK")]},
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["status"] == "partial_success", response.text
    assert (result["failed"], result["inserted"]) == (1, 1), response.text
    assert result["errors"][0]["code"] == "broken_relations"
    async with database() as db:
        model = Order if entity == "order" else Deal
        assert await db.scalar(select(model.id).where(model.external_id == "BAD-LINK")) is None
        assert await db.scalar(select(model.id).where(model.external_id == "GOOD-LINK")) is not None
        assert await db.scalar(select(SourceRecord.id).where(SourceRecord.external_id == "BAD-LINK")) is None


@pytest.mark.parametrize("entity", ["order", "deal"])
async def test_rejected_update_preserves_snapshot_version_and_valid_replay(
    client, database, minimal_admin, links, entity
):
    data = order_data(links) if entity == "order" else deal_data(links)
    if entity == "order":
        data.update(order_number="UPDATABLE-LINK", standard_hours_per_unit=1)
    source = "erp" if entity == "order" else "crm"
    path = f"/api/v1/integrations/{source}/import"
    first = record(entity, data)
    response = await client.post(path, headers=minimal_admin, json={"records": [first]})
    assert response.json()["data"]["inserted"] == 1, response.text
    async with database() as db:
        model = Order if entity == "order" else Deal
        obj = await db.scalar(select(model).where(model.external_id == "LINK-IMPORT"))
        identifier = obj.id
        version = getattr(obj, "version", None)
        original_updated = obj.updated_at
        original = obj.customer_id
        provenance = await db.scalar(select(SourceRecord).where(SourceRecord.external_id == "LINK-IMPORT"))
        old_hash, old_time = provenance.content_hash, provenance.event_at
    bad = record(entity, {**data, "customer_id": str(links.customers[1].id)})
    rejected = await client.post(path, headers=minimal_admin, json={"records": [bad]})
    assert rejected.json()["data"]["failed"] == 1, rejected.text
    assert rejected.json()["data"]["errors"][0]["code"] == "broken_relations"
    async with database() as db:
        obj = await db.get(model, identifier)
        assert (obj.customer_id, getattr(obj, "version", None), obj.updated_at) == (
            original,
            version,
            original_updated,
        )
        provenance = await db.scalar(select(SourceRecord).where(SourceRecord.external_id == "LINK-IMPORT"))
        assert (provenance.content_hash, provenance.event_at) == (old_hash, old_time)
    replay = await client.post(path, headers=minimal_admin, json={"records": [first]})
    assert replay.json()["data"]["skipped"] == 1, replay.text
    changed = record(entity, {**data, ("amount" if entity == "order" else "expected_amount"): 25})
    update = await client.post(path, headers=minimal_admin, json={"records": [changed]})
    assert update.json()["data"]["updated"] == 1, update.text
    async with database() as db:
        obj = await db.get(model, identifier)
        if version is not None:
            assert obj.version == version + 1
        assert getattr(obj, "amount" if entity == "order" else "expected_amount") == 25


async def test_import_accepts_unspecified_deal_product(client, minimal_admin, links):
    data = deal_data(links)
    data["product_id"] = None
    response = await client.post(
        "/api/v1/integrations/crm/import", headers=minimal_admin, json={"records": [record("deal", data)]}
    )
    assert response.json()["data"]["inserted"] == 1, response.text


@pytest.mark.parametrize("entity", ["order", "deal"])
async def test_import_cannot_bypass_reverse_link_check_by_omitting_reference(
    client, database, minimal_admin, links, entity
):
    data = order_data(links) if entity == "order" else deal_data(links)
    if entity == "order":
        data.update(order_number="REVERSE-UPDATABLE", standard_hours_per_unit=1)
    source = "erp" if entity == "order" else "crm"
    path = f"/api/v1/integrations/{source}/import"
    inserted = await client.post(path, headers=minimal_admin, json={"records": [record(entity, data)]})
    assert inserted.json()["data"]["inserted"] == 1, inserted.text
    async with database() as db:
        model = Order if entity == "order" else Deal
        obj = await db.scalar(select(model).where(model.external_id == "LINK-IMPORT"))
        identifier = obj.id
        if entity == "order":
            linked = await db.get(Deal, links.free_deal.id)
            linked.order_id = identifier
        else:
            linked = await db.get(Order, links.free_order.id)
            linked.crm_deal_id = identifier
        await db.commit()
    invalid = {
        **data,
        "product_id": str(links.products[1].id),
        ("crm_deal_id" if entity == "order" else "order_id"): None,
    }
    rejected = await client.post(path, headers=minimal_admin, json={"records": [record(entity, invalid)]})
    assert rejected.json()["data"]["failed"] == 1, rejected.text
    assert rejected.json()["data"]["errors"][0]["code"] == "broken_relations"
    async with database() as db:
        obj = await db.get(model, identifier)
        assert obj.product_id == links.products[0].id
        assert getattr(obj, "crm_deal_id" if entity == "order" else "order_id") is not None
