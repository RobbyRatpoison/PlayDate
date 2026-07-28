"""Review confidence weighting (scrapers._weighted_score) and
Steam-style review labels (utils.review_score_label)."""
import pytest

from scrapers import _weighted_score
from utils import review_score_label


def test_zero_reviews_scores_zero():
    assert _weighted_score(100, 0) == 0


def test_neutral_score_stays_neutral_regardless_of_count():
    assert _weighted_score(50, 1) == 50
    assert _weighted_score(50, 100000) == 50


def test_low_count_pulled_toward_fifty():
    # 100% with 9 reviews: log10(10)=1 → halfway pulled back → 75.
    assert _weighted_score(100, 9) == 75
    # 100% with 99 reviews: log10(100)=2 → quarter pulled back.
    assert _weighted_score(100, 99) == 88


def test_negative_scores_pulled_up_toward_fifty():
    assert _weighted_score(0, 9) == 25


def test_high_count_approaches_raw_score():
    assert _weighted_score(90, 999999) - 90 <= 1


def test_pull_weakens_as_count_grows():
    scores = [_weighted_score(100, n) for n in (9, 99, 999, 9999)]
    assert scores == sorted(scores)
    assert scores[0] < scores[-1] <= 100


@pytest.mark.parametrize("percent,total,label", [
    (100, 0,    'No Reviews'),
    (100, 9,    'Not Enough Reviews'),
    (96,  500,  'Overwhelmingly Positive'),
    (96,  499,  'Very Positive'),   # count too low for Overwhelmingly
    (85,  100,  'Very Positive'),
    (85,  20,   'Positive'),        # positive but fewer than 50 reviews
    (75,  100,  'Mostly Positive'),
    (55,  100,  'Mixed'),
    (30,  100,  'Mostly Negative'),
    (10,  600,  'Overwhelmingly Negative'),
    (10,  60,   'Very Negative'),
    (10,  20,   'Negative'),
])
def test_review_score_label(percent, total, label):
    assert review_score_label(percent, total) == label
