from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

from app.models import CapacityPlan, Customer, DataQualityIssue, Department, Order, Product, SourceSyncRun


def ready(source):
    now = datetime.now(UTC)
    return SourceSyncRun(source_name=source, status="success", started_at=now, finished_at=now, errors=[])


async def test_empty_loaded_data_differs_from_unloaded_source(client, database, minimal_admin):
    response = await client.get("/api/v1/dashboard", headers=minimal_admin)
    kpis = {row["code"]: row for row in response.json()["data"]["kpis"]}
    assert kpis["revenue"]["actual"] is None
    async with database() as db:
        db.add_all([ready("erp"), ready("crm")])
        await db.commit()
    response = await client.get("/api/v1/dashboard", headers=minimal_admin)
    assert response.status_code == 200, response.text
    kpis = {row["code"]: row for row in response.json()["data"]["kpis"]}
    assert kpis["revenue"]["actual"] == 0
    assert kpis["active_customers"]["actual"] == 0
    assert kpis["repeat_purchase_rate"]["actual"] is None
    assert kpis["repeat_purchase_rate"]["status"] == "no_data"
    future = (datetime.now(UTC) + timedelta(days=3)).date().isoformat()
    response = await client.get(
        "/api/v1/dashboard", headers=minimal_admin, params={"date_from": future, "date_to": future}
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["critical_alerts_count"] == 0


async def test_minsk_inclusive_dates_and_first_purchase_in_selected_scope(client, database, minimal_admin):
    async with database() as db:
        own = Department(code="own", name="Own", is_active=True)
        other = Department(code="other", name="Other", is_active=True)
        customer = Customer(
            name="Scope customer",
            customer_type="b2b",
            segment="test",
            acquisition_channel="web",
            first_order_at=datetime(2026, 3, 1, tzinfo=UTC),
        )
        product = Product(
            code="edge",
            name="Product",
            category="test",
            standard_price=Decimal(10),
            standard_hours_per_unit=Decimal(1),
            is_active=True,
        )
        db.add_all([own, other, customer, product, ready("erp"), ready("crm")])
        await db.flush()
        dates = [
            datetime(2026, 3, 1, tzinfo=UTC),
            datetime(2026, 3, 4, 21, tzinfo=UTC),
            datetime(2026, 3, 5, 20, 59, 59, tzinfo=UTC),
            datetime(2026, 3, 5, 21, tzinfo=UTC),
        ]
        for index, completed in enumerate(dates):
            db.add(
                Order(
                    order_number=f"EDGE-{index}",
                    customer_id=customer.id,
                    product_id=product.id,
                    department_id=other.id if index == 0 else own.id,
                    channel="web",
                    quantity=1,
                    standard_hours_per_unit=1,
                    amount=10,
                    status="completed",
                    due_at=completed + timedelta(hours=1),
                    completed_at=completed,
                    created_at=completed - timedelta(hours=1),
                )
            )
        await db.commit()
        own_id = str(own.id)
    params = {"date_from": "2026-03-05", "date_to": "2026-03-05", "department_id": own_id}
    response = await client.get("/api/v1/dashboard", params=params, headers=minimal_admin)
    assert response.status_code == 200, response.text
    values = {row["code"]: row["actual"] for row in response.json()["data"]["kpis"]}
    assert values["revenue"] == 20
    assert values["new_customers"] == 1
    assert values["repeat_purchase_rate"] == 100
    company = await client.get(
        "/api/v1/dashboard",
        params={k: v for k, v in params.items() if k != "department_id"},
        headers=minimal_admin,
    )
    assert next(k for k in company.json()["data"]["kpis"] if k["code"] == "new_customers")["actual"] == 0
    listed = await client.get("/api/v1/customers", params=params, headers=minimal_admin)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["first_order_at"].startswith("2026-03-04T21:00:00")
    invalid = await client.get(
        "/api/v1/customers?date_from=2026-03-06&date_to=2026-03-05", headers=minimal_admin
    )
    assert invalid.status_code == 422


async def test_forecast_rejects_completely_missing_capacity_for_demanded_pair(client, database, seeded):
    async with database() as db:
        row = await db.scalar(select(CapacityPlan).where(CapacityPlan.plan_date > date.today()))
        await db.execute(
            delete(CapacityPlan).where(
                CapacityPlan.department_id == row.department_id,
                CapacityPlan.product_id == row.product_id,
                CapacityPlan.plan_date > date.today(),
            )
        )
        await db.commit()
    response = await client.get("/api/v1/forecast", headers=seeded)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "no_data"
    assert all(row["available_capacity"] is None for row in response.json()["data"]["items"])


async def test_checking_erp_does_not_close_unchecked_finance_issue(client, database, minimal_admin):
    async with database() as db:
        issue = DataQualityIssue(
            source_name="finance",
            check_type="missing_fields",
            severity="critical",
            description="Unrelated finance issue",
            affected_records=1,
            status="open",
            checked_at=datetime.now(UTC),
            details={},
            fingerprint="finance:persisted_missing",
        )
        db.add(issue)
        await db.commit()
        identifier = issue.id
    response = await client.post("/api/v1/data-quality/check", headers=minimal_admin, json={"source": "erp"})
    assert response.status_code == 200, response.text
    async with database() as db:
        assert (await db.get(DataQualityIssue, identifier)).status == "open"
