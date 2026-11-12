"""Import a synthetic JSON batch or CSV with entity_type,external_id,event_at,data columns."""

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select

from app.db.session import get_engine, get_session_factory
from app.models import User
from app.services.imports import REGISTRY, import_records


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=REGISTRY)
    parser.add_argument("path", type=Path)
    parser.add_argument("--actor-email", default="admin@fotoprint.demo")
    args = parser.parse_args()
    if args.path.stat().st_size > 5 * 1024 * 1024:
        parser.error("Maximum file size: 5 MiB")
    if args.path.suffix.lower() == ".csv":
        with args.path.open(newline="", encoding="utf-8-sig") as stream:
            records = []
            for row in csv.DictReader(stream):
                if set(row) != {"entity_type", "external_id", "event_at", "data"}:
                    parser.error("CSV requires entity_type,external_id,event_at,data columns")
                records.append({**row, "data": json.loads(row["data"])})
    else:
        data = json.loads(args.path.read_text())
        records = data["records"] if isinstance(data, dict) else data
    if (
        not isinstance(records, list)
        or len(records) > 1000
        or any(not isinstance(row, dict) for row in records)
    ):
        parser.error("Expected a list of at most 1000 records")
    async with get_session_factory()() as db:
        actor = await db.scalar(
            select(User).where(
                User.email == args.actor_email.lower(), User.role == "admin", User.is_active.is_(True)
            )
        )
        if not actor:
            parser.error("Active administrator not found; initialize demo users first")
        result = await import_records(db, args.source, records, actor)
        print(
            json.dumps(
                {
                    "run_id": str(result.id),
                    "status": result.status,
                    "inserted": result.records_inserted,
                    "updated": result.records_updated,
                    "skipped": result.records_skipped,
                    "failed": result.records_failed,
                },
                ensure_ascii=False,
            )
        )
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
