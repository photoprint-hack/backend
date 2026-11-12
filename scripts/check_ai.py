"""Check configuration, or use --live for one synthetic OpenRouter request. No database access."""

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.services.impact import provider


async def main(live=False):
    if not get_settings().openrouter_api_key:
        print("AI_NOT_CONFIGURED: set OPENROUTER_API_KEY in the private environment")
        return 2
    if not live:
        print("AI_CONFIGURED: use --live to test one synthetic request")
        return 0
    ref = str(uuid4())
    context = {
        "synthetic_demo": True,
        "nodes": [{"id": ref, "type": "metric", "status": "critical"}],
        "metric": {"code": "on_time_orders", "actual": 82, "target": 95},
        "verified_facts": [{"text": "Synthetic on-time orders: 82%, target: 95%", "refs": [ref]}],
        "calculated_dependencies": [],
        "suggested_responsible": None,
    }
    try:
        content, model = await provider.generate(context)
        print(f"AI_OK: model={model}; structured_fields={len(content)}; synthetic_request=true")
        return 0
    except ApiError as error:
        print(f"AI_FAILED: code={error.code}; status={error.status}")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    raise SystemExit(asyncio.run(main(parser.parse_args().live)))
