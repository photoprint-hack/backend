from datetime import UTC, datetime

from sqlalchemy import inspect, select

from app.models import Alert, Customer, Decision, Department, Order, Product, Task, User


def columns(obj, exclude=()) -> dict:
    return {
        column.key: getattr(obj, column.key)
        for column in inspect(type(obj)).columns
        if column.key not in exclude
    }


def actions(obj, user) -> list[str]:
    result = ["read"]
    if user.role in {"admin", "director", "manager"}:
        if isinstance(obj, (Order, Decision, Task)) and obj.status not in {"completed", "cancelled"}:
            result += ["update", "cancel"]
            if obj.status == "new":
                result += ["start"]
            if isinstance(obj, Decision):
                if obj.status == "in_progress":
                    result += ["submit_review"]
                if obj.status == "needs_review":
                    result += ["verify"]
            elif isinstance(obj, Task) and obj.status == "in_progress":
                result += ["complete"]
        if isinstance(obj, Task) and user.role == "admin":
            result += ["archive"]
    elif user.role == "employee" and isinstance(obj, Task) and obj.assignee_id == user.id:
        if obj.status == "new":
            result += ["start"]
        if obj.status == "in_progress":
            result += ["complete"]
    return result


async def serialize_many(db, objects, user) -> list[dict]:
    if not objects:
        return []
    refs = {User: set(), Department: set(), Customer: set(), Product: set(), Decision: set(), Alert: set()}
    for obj in objects:
        for model, fields in [
            (User, ("owner_id", "created_by", "assignee_id")),
            (Department, ("department_id",)),
            (Customer, ("customer_id",)),
            (Product, ("product_id",)),
            (Decision, ("decision_id",)),
            (Alert, ("alert_id",)),
        ]:
            for field in fields:
                value = getattr(obj, field, None)
                if value:
                    refs[model].add(value)
    cache = {}
    for model, identifiers in refs.items():
        cache[model] = (
            {row.id: row for row in (await db.scalars(select(model).where(model.id.in_(identifiers)))).all()}
            if identifiers
            else {}
        )

    def ref(model, identifier):
        found = cache[model].get(identifier)
        if not found:
            return None
        return {
            "id": found.id,
            "full_name" if model is User else "name": found.full_name
            if model is User
            else found.title
            if model in {Decision, Alert}
            else found.name,
        }

    results = []
    for obj in objects:
        item = columns(obj, exclude={"deleted_at"})
        if isinstance(obj, Order):
            item.update(
                customer_name=cache[Customer][obj.customer_id].name,
                product_name=cache[Product][obj.product_id].name,
                department_name=cache[Department][obj.department_id].name,
            )
        if isinstance(obj, Decision):
            item.update(
                owner=ref(User, obj.owner_id),
                creator=ref(User, obj.created_by),
                department=ref(Department, obj.department_id),
            )
        if isinstance(obj, Task):
            item.update(
                assignee=ref(User, obj.assignee_id),
                creator=ref(User, obj.created_by),
                department=ref(Department, obj.department_id),
                decision=ref(Decision, obj.decision_id),
                is_overdue=obj.deadline < datetime.now(UTC) and obj.status in {"new", "in_progress"},
            )
        if isinstance(obj, (Decision, Task)):
            alert = cache[Alert].get(obj.alert_id)
            visible = user.role in {"admin", "director", "analyst"} or (
                user.role == "manager" and alert and alert.department_id == user.department_id
            )
            item["alert_title"] = alert.title if alert and visible else None
        if isinstance(obj, (Order, Decision, Task)):
            item["allowed_actions"] = actions(obj, user)
        results.append(item)
    return results
