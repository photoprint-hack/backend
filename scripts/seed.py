"""Insert synthetic demo data; never reset existing data."""

import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.db.session import get_engine, get_session_factory
from app.seed.service import seed


async def main():
    config = get_settings()
    passwords = {
        role: getattr(config, "demo_" + role + "_password").get_secret_value()
        if getattr(config, "demo_" + role + "_password")
        else ""
        for role in ["admin", "director", "manager", "analyst", "employee"]
    }
    async with get_session_factory()() as db:
        result = await seed(
            db,
            passwords=passwords,
            reference=date.fromisoformat(config.demo_reference_date) if config.demo_reference_date else None,
        )
        await db.commit()
        print(
            "Synthetic data ready:",
            result["inserted"],
            "new records; reference date",
            result["reference_date"],
        )
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
