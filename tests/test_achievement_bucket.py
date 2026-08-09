"""Home page achievement chart widget bucketing (index.achievement_bucket)."""
import pytest

from index import achievement_bucket


@pytest.mark.parametrize("unlocked,total,bucket", [
    (0,   10, '0-25%'),
    (2,   10, '0-25%'),   # 20%, still first bucket
    (25, 100, '0-25%'),   # exact lower boundary
    (26, 100, '26-50%'),  # just past the lower boundary
    (50, 100, '26-50%'),  # exact boundary
    (51, 100, '51-75%'),  # just past
    (75, 100, '51-75%'),  # exact boundary
    (76, 100, '76-100%'), # just past
    (100, 100, '76-100%'),
    (1,   3,  '26-50%'),  # 33.3% — non-integer percentage
])
def test_achievement_bucket(unlocked, total, bucket):
    assert achievement_bucket(unlocked, total) == bucket


def test_achievement_bucket_null_unlocked_treated_as_zero():
    assert achievement_bucket(None, 10) == '0-25%'
