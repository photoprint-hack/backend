"""Versioned demo business calendar. Stored deadlines are never recalculated implicitly."""

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Minsk")
RESPONSE_MINUTES = {"critical": 30, "high": 240, "medium": 480, "low": 960}


def version(holidays: list[date]) -> str:
    return hashlib.sha256(
        json.dumps(["Minsk:Mon-Fri:09-13,14-18:v1", *sorted(map(str, holidays))]).encode()
    ).hexdigest()


def add_working_minutes(start: datetime, minutes: int, holidays: list[date] = ()) -> datetime:
    if start.tzinfo is None or minutes < 0:
        raise ValueError("Expected aware start and nonnegative minutes")
    cursor = start.astimezone(ZONE)
    remaining = timedelta(minutes=minutes)
    excluded = set(holidays)
    for _ in range(36600):
        day = cursor.date()
        if day.weekday() < 5 and day not in excluded:
            for left, right in [(time(9), time(13)), (time(14), time(18))]:
                lo, hi = (datetime.combine(day, x, ZONE) for x in (left, right))
                current = max(cursor, lo)
                if current < hi:
                    if remaining <= hi - current:
                        return (current + remaining).astimezone(UTC)
                    remaining -= hi - current
        cursor = datetime.combine(day + timedelta(days=1), time.min, ZONE)
    raise ValueError("Business calendar has no available interval")
