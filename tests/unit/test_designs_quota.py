"""Unit tests for services/designs/quota.py (D-14): UTC-day arithmetic, the accepted
count (failed rows excluded), the 429 + Retry-After refusal, owner exemption and the
/me/quota status shape. The session is a MagicMock: only the scalar the code reads is
configured."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from tests.unit.designs_testkit import load_designs

NOW = datetime(2026, 9, 18, 21, 30, tzinfo=timezone.utc)
MIDNIGHT = datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def quota():
    return load_designs().quota


def _db(scalar):
    db = MagicMock()
    db.execute.return_value.scalar.return_value = scalar
    return db


def test_utc_day_start(quota):
    assert quota.utc_day_start(NOW) == MIDNIGHT
    assert quota.utc_day_start(MIDNIGHT) == MIDNIGHT
    # a non-UTC instant is converted before truncating
    assert quota.utc_day_start(NOW.astimezone(timezone.utc)) == MIDNIGHT


def test_seconds_until_utc_midnight(quota):
    assert quota.seconds_until_utc_midnight(NOW) == 9000  # 02:30 left
    assert quota.seconds_until_utc_midnight(MIDNIGHT) == 86400
    assert quota.seconds_until_utc_midnight(datetime(2026, 9, 18, 23, 59, 59, 999_999, tzinfo=timezone.utc)) >= 1


def test_count_accepted_today_reads_scalar(quota):
    assert quota.count_accepted_today(_db(4), "c@x.io", NOW) == 4
    assert quota.count_accepted_today(_db(None), "c@x.io", NOW) == 0


def test_check_quota_allows_under_limit(quota):
    assert quota.check_quota(_db(9), "c@x.io", "customer", 10, NOW) == 9


def test_check_quota_rejects_at_limit(quota):
    with pytest.raises(HTTPException) as ei:
        quota.check_quota(_db(10), "c@x.io", "customer", 10, NOW)
    assert ei.value.status_code == 429
    assert ei.value.detail == "Daily limit of 10 generations reached"
    assert ei.value.headers["Retry-After"] == "9000"


def test_check_quota_owner_exempt(quota):
    db = _db(999)
    assert quota.check_quota(db, "admin@x.io", "owner", 10, NOW) == 0
    db.execute.assert_not_called()


def test_check_quota_zero_limit_disables(quota):
    assert quota.check_quota(_db(999), "c@x.io", "customer", 0, NOW) == 0


def test_quota_status_shape(quota):
    assert quota.quota_status(_db(3), "c@x.io", "customer", 10, NOW) == {
        "limit": 10,
        "used": 3,
        "remaining": 7,
        "resets_at": datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc),
        "exempt": False,
    }
    owner = quota.quota_status(_db(3), "admin@x.io", "owner", 10, NOW)
    assert owner["remaining"] is None
    assert owner["exempt"] is True
    assert owner["used"] == 0
