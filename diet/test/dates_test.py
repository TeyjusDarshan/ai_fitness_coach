"""parse_timestamp: Supabase timestamps on Pythons older than 3.11 (the VM)."""
from datetime import datetime, timedelta, timezone

import pytest

from diet.dates import parse_timestamp

UTC = timezone.utc


@pytest.mark.parametrize("text, expected", [
    # Postgres drops trailing zeros: .240480 comes back as .24048 (5 digits).
    ("2026-11-27T04:10:30.24048+00:00", datetime(2026, 11, 27, 4, 10, 30, 240480, UTC)),
    ("2026-11-27T04:10:30.974536+00:00", datetime(2026, 11, 27, 4, 10, 30, 974536, UTC)),
    ("2026-11-27T04:10:30.5+00:00", datetime(2026, 11, 27, 4, 10, 30, 500000, UTC)),
    ("2026-11-27T04:10:30+00:00", datetime(2026, 11, 27, 4, 10, 30, tzinfo=UTC)),
    ("2026-11-27T04:10:30.1234Z", datetime(2026, 11, 27, 4, 10, 30, 123400, UTC)),
    ("2026-11-27 04:10:30.12+00:00", datetime(2026, 11, 27, 4, 10, 30, 120000, UTC)),  # space separator
    ("2026-11-27T09:40:30.24048+05:30", datetime(2026, 11, 27, 4, 10, 30, 240480, UTC)),
])
def test_parses_every_fraction_length_supabase_returns(text, expected):
    parsed = parse_timestamp(text)
    assert parsed == expected
    assert parsed.utcoffset() is not None


def test_a_naive_timestamp_stays_naive():
    assert parse_timestamp("2026-11-27T04:10:30.2") == datetime(2026, 11, 27, 4, 10, 30, 200000)


def test_parsed_times_compare_with_now():
    assert parse_timestamp("2026-11-27T04:10:30.24048+00:00") > datetime(2026, 11, 26, tzinfo=UTC) - timedelta(days=1)
