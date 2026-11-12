"""Continuous internal notification/SLA worker. Uses the configured database; never seeds/migrates."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.db.session import get_engine, get_session_factory
from app.services.impact.notifications import tick


async def main(once=False):
    factory = get_session_factory()
    try:
        while True:
            try:
                await tick(factory)
            except Exception:
                # Driver exceptions can contain DSNs/SQL parameters. Do not log exception contents.
                logging.getLogger("photoprint.worker").error(
                    "Worker iteration failed; uncommitted changes rolled back"
                )
                if once:
                    raise SystemExit(1) from None
            if once:
                return
            await asyncio.sleep(get_settings().worker_poll_seconds)
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    asyncio.run(main(parser.parse_args().once))
