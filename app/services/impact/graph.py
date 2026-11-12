import hashlib
import json
from collections import deque
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_, select

from app.core.exceptions import ApiError
from app.core.permissions import department_scope, scope_statement
from app.models import Alert, Decision, Department, Order, OrderEvent, Task
from app.models.impact import MaryEvent
from app.schemas.shared.query import BusinessQuery
from app.services import analytics
from app.services.impact.structure import PROCESSES, REVISION


def digest(value):
    return hashlib.sha256(
        json.dumps(jsonable_encoder(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def explore(graph, origin, depth=1, direction="both", edge_types=(), target=None):
    nodes = {n["id"]: n for n in graph["nodes"]}
    if origin not in nodes or target and target not in nodes:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Узел не найден в разрешённом контексте")
    adjacent = {key: [] for key in nodes}
    for edge in graph["edges"]:
        if edge_types and edge["type"] not in edge_types:
            continue
        if direction in {"out", "both"}:
            adjacent[edge["source"]].append((edge["target"], edge))
        if direction in {"in", "both"}:
            adjacent[edge["target"]].append((edge["source"], edge))
    visited, parents = {origin}, {}
    queue = deque([(origin, 0)])
    while queue:
        current, distance = queue.popleft()
        if current == target:
            break
        if distance == depth:
            continue
        for other, edge in adjacent[current]:
            if other not in visited:
                visited.add(other)
                parents[other] = (current, edge)
                queue.append((other, distance + 1))
    path_edges = None
    if target:
        visited, path_edges = set(), []
        if target == origin or target in parents:
            current = target
            visited.add(current)
            while current != origin:
                current, edge = parents[current]
                visited.add(current)
                path_edges.append(edge)
            path_edges.reverse()
    edges = (
        path_edges
        if path_edges is not None
        else [
            e
            for e in graph["edges"]
            if e["source"] in visited
            and e["target"] in visited
            and (not edge_types or e["type"] in edge_types)
        ]
    )
    return {**graph, "nodes": [n for n in graph["nodes"] if n["id"] in visited], "edges": edges}


async def build(db, query, user):
    scope = department_scope(user, query.department_id)
    start, end, lo, hi = analytics.period(query)
    context = {"date_from": start, "date_to": end, "department_id": scope, "product_id": query.product_id}
    nodes, edges = {}, []
    truncated = False

    def node(key, kind, label, *, ref=None, status=None, updated=None, metadata=None):
        nodes[key] = dict(
            id=key,
            type=kind,
            label=label,
            description=label,
            entity_ref=ref,
            status=status,
            context=context,
            updated_at=updated,
            allowed_actions=["read", "neighbors"]
            + (["analyze"] if kind == "metric" and user.role != "employee" else [])
            + (
                ["create_action"]
                if ref
                and user.role in {"admin", "director", "manager"}
                and ref["type"] in {"metric", "order", "task", "decision", "alert"}
                else []
            ),
            metadata=metadata or {},
        )

    def link(source, target, kind, evidence="verified", refs=None):
        if source in nodes and target in nodes:
            edges.append(
                dict(
                    id=digest([source, target, kind])[:32],
                    source=source,
                    target=target,
                    type=kind,
                    evidence_type=evidence,
                    description="Связь по данным платформы; не доказательство причинности",
                    evidence_source="platform",
                    evidence_refs=refs or [source, target],
                )
            )

    if user.role != "employee":
        values, context = await analytics.calculate(db, query, user)
        previous = None
        try:
            size = (end - start).days + 1
            previous, _ = await analytics.calculate(
                db,
                BusinessQuery(
                    date_from=start - timedelta(days=size),
                    date_to=start - timedelta(days=1),
                    department_id=scope,
                    product_id=query.product_id,
                ),
                user,
            )
        except (OverflowError, ValueError):
            pass
        old = {v["code"]: v for v in previous or []}
        for value in values:
            value["updated_at"] = value["source_updated_at"]
            code = value["code"]
            node(
                "metric:" + code,
                "metric",
                value["name"],
                ref={"type": "metric", "id": code},
                status=value["status"],
                updated=value["updated_at"],
                metadata={"kpi": value, "previous_actual": old.get(code, {}).get("actual")},
            )
        for code, (label, metrics, source) in PROCESSES.items():
            node("source:" + source, "source", source.upper(), metadata={"source_code": source})
            node("process:" + code, "process", label)
            link("source:" + source, "process:" + code, "feeds")
            for metric in metrics:
                link("process:" + code, "metric:" + metric, "produces", "calculated")
        stmt = select(Department).where(Department.is_active.is_(True))
        if scope:
            stmt = stmt.where(Department.id == scope)
        for row in (await db.scalars(stmt.order_by(Department.id).limit(20))).all():
            node(
                "department:" + str(row.id),
                "department",
                row.name,
                ref={"type": "department", "id": str(row.id)},
            )

    dynamic = []
    for model, label in [(Order, "order"), (Task, "task"), (Decision, "decision")]:
        stmt = scope_statement(select(model), model, user, query.department_id)
        if model is Order:
            stmt = stmt.where(
                or_(
                    (Order.created_at >= lo) & (Order.created_at < hi),
                    (Order.completed_at >= lo) & (Order.completed_at < hi),
                )
            )
            if query.product_id:
                stmt = stmt.where(Order.product_id == query.product_id)
        else:
            if model is Task:
                stmt = stmt.where(Task.deleted_at.is_(None))
            if query.product_id:
                condition = model.alert_id.in_(select(Alert.id).where(Alert.product_id == query.product_id))
                if model is Task:
                    condition = condition | Task.order_id.in_(
                        select(Order.id).where(Order.product_id == query.product_id)
                    )
                stmt = stmt.where(condition)
            stmt = stmt.where(model.created_at < hi)
        rows = (await db.scalars(stmt.order_by(model.updated_at.desc(), model.id).limit(13))).all()
        truncated |= len(rows) > 12
        for row in rows[:12]:
            key = label + ":" + str(row.id)
            node(
                key,
                "decision" if model is Decision else "entity",
                getattr(row, "title", getattr(row, "order_number", label)),
                ref={"type": label, "id": str(row.id)},
                status=row.status,
                updated=row.updated_at,
                metadata={"entity_type": label},
            )
            dynamic.append((label, row, key))
    for label, row, key in dynamic:
        link(key, "department:" + str(row.department_id), "belongs_to")
        if label == "order":
            link("process:production", key, "produces")
            for metric in ("on_time_orders", "revenue"):
                link(key, "metric:" + metric, "may_affect", "hypothesis")
        if label == "task":
            if row.order_id:
                link(key, "order:" + str(row.order_id), "depends_on")
            if row.decision_id:
                link("decision:" + str(row.decision_id), key, "mitigated_by")
        if label == "decision" and row.alert_id:
            link("alert:" + str(row.alert_id), key, "mitigated_by")
    # Events are projected only when their parent order is already permitted and selected.
    orders = [row.id for label, row, _ in dynamic if label == "order"]
    if orders and user.role != "employee":
        stmt = select(OrderEvent).where(
            OrderEvent.order_id.in_(orders), OrderEvent.occurred_at >= lo, OrderEvent.occurred_at < hi
        )
        if user.role == "manager":
            stmt = stmt.where(OrderEvent.department_id == user.department_id)
        for row in (
            await db.scalars(stmt.order_by(OrderEvent.occurred_at.desc(), OrderEvent.id).limit(12))
        ).all():
            key = "event:" + str(row.id)
            node(
                key,
                "event",
                row.event_type,
                ref={"type": "order_event", "id": str(row.id)},
                metadata={"occurred_at": row.occurred_at},
            )
            link("order:" + str(row.order_id), key, "produces")
    if user.role != "employee":
        stmt = scope_statement(select(Alert), Alert, user, query.department_id).where(
            Alert.period_start <= end, Alert.period_end >= start
        )
        if query.product_id:
            stmt = stmt.where(Alert.product_id == query.product_id)
        for row in (await db.scalars(stmt.order_by(Alert.updated_at.desc(), Alert.id).limit(12))).all():
            key = "alert:" + str(row.id)
            node(
                key,
                "risk",
                row.title,
                ref={"type": "alert", "id": str(row.id)},
                status=row.status,
                updated=row.updated_at,
            )
            link("metric:" + row.metric_code, key, "produces", "calculated")
            for label, obj, other in dynamic:
                if label == "decision" and obj.alert_id == row.id:
                    link(key, other, "mitigated_by")
        stmt = select(MaryEvent).where(MaryEvent.occurred_at >= lo, MaryEvent.occurred_at < hi)
        if scope:
            stmt = stmt.where(MaryEvent.department_id == scope)
        if query.product_id:
            stmt = stmt.where(
                MaryEvent.order_id.in_(select(Order.id).where(Order.product_id == query.product_id))
            )
        for row in (
            await db.scalars(stmt.order_by(MaryEvent.occurred_at.desc(), MaryEvent.id).limit(8))
        ).all():
            node("source:mary", "source", "Mary (simulated)", metadata={"simulated": True})
            key = "mary_event:" + str(row.id)
            node(
                key,
                "event",
                row.event_type,
                ref={"type": "mary_event", "id": str(row.id)},
                metadata={"simulated": True},
            )
            link("source:mary", key, "feeds")
            if row.order_id:
                link(key, "order:" + str(row.order_id), "belongs_to")
    selected = list(nodes.values())[:200]
    ids = {n["id"] for n in selected}
    permitted = [
        e for e in edges if e["source"] in ids and e["target"] in ids and set(e["evidence_refs"]) <= ids
    ]
    visual_ids = {n["id"]: str(uuid5(NAMESPACE_URL, "photoprint:impact:" + n["id"])) for n in selected}
    for n in selected:
        n["id"] = visual_ids[n["id"]]
    for e in permitted:
        e["id"] = str(uuid5(NAMESPACE_URL, "photoprint:impact:edge:" + e["id"]))
        e["source"], e["target"] = visual_ids[e["source"]], visual_ids[e["target"]]
        e["evidence_refs"] = [visual_ids[ref] for ref in e["evidence_refs"]]
    content = {"nodes": selected, "edges": permitted[:400], "context": context}
    return {
        **content,
        "graph_revision": digest([REVISION, content]),
        "generated_at": datetime.now(UTC),
        "truncated": truncated or len(nodes) > 200 or len(permitted) > 400,
    }
