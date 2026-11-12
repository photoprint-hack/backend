from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.impact.calendar import add_working_minutes, version

ZONE = ZoneInfo("Europe/Minsk")


@pytest.mark.parametrize(
    "start,minutes,expected,holidays",
    [
        ("2026-11-13T17:45", 30, "2026-11-16T09:15", []),
        ("2026-11-13T17:45", 30, "2026-11-17T09:15", [date(2026, 11, 16)]),
        ("2026-11-12T12:45", 30, "2026-11-12T14:15", []),
        ("2026-11-12T13:30", 30, "2026-11-12T14:30", []),
        ("2026-11-14T12:00", 480, "2026-11-16T18:00", []),
        ("2026-11-12T08:00", 30, "2026-11-12T09:30", []),
        ("2026-11-12T18:00", 30, "2026-11-13T09:30", []),
    ],
)
def test_business_intervals(start, minutes, expected, holidays):
    value = add_working_minutes(datetime.fromisoformat(start).replace(tzinfo=ZONE), minutes, holidays)
    assert value == datetime.fromisoformat(expected).replace(tzinfo=ZONE)
    assert value.utcoffset().total_seconds() == 0


def test_version_and_invalid_calendar_arguments():
    assert version([]) != version([date(2026, 11, 16)])
    with pytest.raises(ValueError):
        add_working_minutes(datetime.now(), 30)
