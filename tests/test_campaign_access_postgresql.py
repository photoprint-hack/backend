from datetime import UTC, datetime

from sqlalchemy import select

from app.models import Campaign, Order, SupportInteraction, User


async def test_manager_sees_related_shared_campaigns_without_global_budget(client, database, seeded):
    login = await client.post(
        "/api/v1/auth/login", json={"email": "manager@fotoprint.demo", "password": "SeedPassword123!"}
    )
    headers = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
    department = login.json()["data"]["user"]["department_id"]
    async with database() as db:
        foreign_order = await db.scalar(select(Order).where(Order.department_id != department))
        foreign_campaign = Campaign(
            name="Foreign campaign only",
            channel="website",
            segment="retail",
            budget=54321,
            currency="BYN",
            started_at=datetime.now(UTC),
        )
        db.add(foreign_campaign)
        await db.flush()
        foreign_order.campaign_id = foreign_campaign.id
        foreign_id = str(foreign_campaign.id)
        await db.commit()
    manager = await client.get("/api/v1/campaigns?page_size=100", headers=headers)
    assert manager.status_code == 200, manager.text
    assert manager.json()["total"] == 5
    assert all(c["budget"] is None for c in manager.json()["items"])
    assert foreign_id not in {c["id"] for c in manager.json()["items"]}
    director = await client.get("/api/v1/campaigns?page_size=100", headers=seeded)
    assert director.status_code == 200, director.text
    assert director.json()["total"] == 6
    assert all(c["budget"] is not None for c in director.json()["items"])
    denied = await client.get(
        "/api/v1/campaigns?department_id=" + str(foreign_order.department_id), headers=headers
    )
    assert denied.status_code == 403


async def test_responsible_department_does_not_grant_access_to_foreign_linked_order(client, database, seeded):
    login = await client.post(
        "/api/v1/auth/login", json={"email": "manager@fotoprint.demo", "password": "SeedPassword123!"}
    )
    headers = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
    async with database() as db:
        manager = await db.scalar(select(User).where(User.role == "manager"))
        order = await db.scalar(select(Order).where(Order.department_id != manager.department_id))
        ticket = SupportInteraction(
            customer_id=order.customer_id,
            order_id=order.id,
            department_id=manager.department_id,
            channel="email",
            topic="Own responsibility for another department order",
            status="open",
            priority="medium",
        )
        db.add(ticket)
        await db.commit()
        ticket_id, order_id = str(ticket.id), str(order.id)
    visible = await client.get("/api/v1/support/interactions/" + ticket_id, headers=headers)
    assert visible.status_code == 200, visible.text
    assert visible.json()["data"]["order_id"] == order_id
    hidden = await client.get("/api/v1/orders/" + order_id, headers=headers)
    assert hidden.status_code == 404
