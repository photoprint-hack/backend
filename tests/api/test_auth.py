from uuid import uuid4

from sqlalchemy import func, select

from app.core.security import hash_password
from app.models import AuditLog, Department, RefreshToken, User


async def account(database, role="director", active=True):
    async with database() as db:
        dept = Department(code="department_" + uuid4().hex[:10], name="Test department")
        db.add(dept)
        await db.flush()
        user = User(
            email=uuid4().hex + "@example.com",
            password_hash=hash_password("PasswordForTests123!"),
            full_name="Test user",
            role=role,
            department_id=dept.id,
            is_active=active,
        )
        db.add(user)
        await db.commit()
        return user


async def signin(client, user):
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "PasswordForTests123!"}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["access_token"]


async def test_login_refresh_reuse_revokes_family(client, database):
    user = await account(database)
    access = await signin(client, user)
    original = client.cookies.get("refresh_token")
    me = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + access})
    assert me.json()["data"]["id"] == str(user.id)
    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    replacement = client.cookies.get("refresh_token")
    assert replacement != original
    reused = await client.post("/api/v1/auth/refresh", headers={"Cookie": "refresh_token=" + original})
    assert reused.status_code == 401
    denied = await client.post("/api/v1/auth/refresh", headers={"Cookie": "refresh_token=" + replacement})
    assert denied.status_code == 401
    async with database() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(RefreshToken)
                .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            )
            == 0
        )


async def test_logout_and_new_login_revoke_old_refresh(client, database):
    user = await account(database)
    access = await signin(client, user)
    old = client.cookies.get("refresh_token")
    access = await signin(client, user)
    denied = await client.post("/api/v1/auth/refresh", headers={"Cookie": "refresh_token=" + old})
    assert denied.status_code == 401
    await signin(client, user)
    response = await client.post("/api/v1/auth/logout", headers={"Authorization": "Bearer " + access})
    assert response.status_code == 200
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_inactive_and_bad_credentials_are_generic(client, database):
    user = await account(database, active=False)
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "PasswordForTests123!"}
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_INVALID_CREDENTIALS"
    async with database() as db:
        assert (
            await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.status == "failure"))
            == 1
        )


async def test_admin_create_and_manager_cannot_read_other_department(client, database):
    admin = await account(database, "admin")
    token = await signin(client, admin)
    response = await client.post(
        "/api/v1/users",
        headers={"Authorization": "Bearer " + token},
        json={
            "email": "created@example.com",
            "full_name": "Created employee",
            "role": "employee",
            "department_id": str(admin.department_id),
            "temporary_password": "SomePassword123!",
        },
    )
    assert response.status_code == 201, response.text
    assert "password" not in response.text
    manager = await account(database, "manager")
    token = await signin(client, manager)
    response = await client.get(
        "/api/v1/users?department_id=" + str(admin.department_id),
        headers={"Authorization": "Bearer " + token},
    )
    assert response.status_code == 403
    response = await client.get("/api/v1/users", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 200
    assert all("email" not in row for row in response.json()["items"])


async def test_concurrent_refresh_reuse_revokes_the_winning_replacement(client, database):
    import asyncio

    user = await account(database)
    await signin(client, user)
    original = client.cookies.get("refresh_token")
    responses = await asyncio.gather(
        client.post("/api/v1/auth/refresh", headers={"Cookie": "refresh_token=" + original}),
        client.post("/api/v1/auth/refresh", headers={"Cookie": "refresh_token=" + original}),
    )
    assert sorted(response.status_code for response in responses) == [200, 401]
    async with database() as db:
        active = await db.scalar(
            select(func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        )
        assert active == 0
