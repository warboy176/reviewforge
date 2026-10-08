"""Tests for ManualSource JSON parsing and honesty guards."""
import json
import os

import pytest

from reviewforge.sources import ManualSource
from reviewforge.models import Business


SAMPLE = {
    "name": "Blue Line Plumbing",
    "category": "Plumber",
    "city": "Boise, ID",
    "phone": "(208) 555-0199",
    "reviews": [
        {"author": "Ana R.", "rating": 5, "text": "Fixed our burst pipe fast.", "date": "2026-01-10"},
        {"author": "Tom K.", "rating": 4, "text": "Fair price, clean work."},
    ],
}


def test_parses_required_and_optional_fields():
    b = ManualSource.from_dict(SAMPLE)
    assert isinstance(b, Business)
    assert b.name == "Blue Line Plumbing"
    assert b.review_count == 2
    assert b.rating_average == 4.5
    # Optional fields absent -> None, not fabricated.
    assert b.website is None
    assert b.hours is None
    # Review optional date preserved / omitted correctly.
    assert b.reviews[0].date == "2026-01-10"
    assert b.reviews[1].date is None
    # source_index assigned for provenance.
    assert [r.source_index for r in b.reviews] == [0, 1]


def test_loads_from_file(tmp_path):
    p = tmp_path / "biz.json"
    p.write_text(json.dumps(SAMPLE), encoding="utf-8")
    b = ManualSource(str(p)).load()
    assert b.name == "Blue Line Plumbing"


def test_missing_required_business_field_raises():
    bad = dict(SAMPLE)
    del bad["phone"]
    with pytest.raises(ValueError, match="phone"):
        ManualSource.from_dict(bad)


def test_review_missing_text_is_rejected_not_fabricated():
    bad = {
        **SAMPLE,
        "reviews": [{"author": "X", "rating": 5}],  # no text
    }
    with pytest.raises(ValueError, match="text"):
        ManualSource.from_dict(bad)


def test_rating_out_of_range_rejected():
    bad = {**SAMPLE, "reviews": [{"author": "X", "rating": 9, "text": "ok"}]}
    with pytest.raises(ValueError, match="0-5"):
        ManualSource.from_dict(bad)


def test_bundled_sample_is_valid():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sample = os.path.join(root, "samples", "business.json")
    b = ManualSource(sample).load()
    assert b.review_count == 5
    assert b.category == "Roofing Contractor"
