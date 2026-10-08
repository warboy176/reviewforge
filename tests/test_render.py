"""Render smoke test + honesty-guard checks.

These run fully offline: the generator's LLM call fails fast against an
unroutable endpoint, so the deterministic fallback template is exercised.
No network required.
"""
import os

from reviewforge.sources import ManualSource
from reviewforge.generator import generate_site_content
from reviewforge.renderer import render_html, write_site

OFFLINE_ENDPOINT = "http://127.0.0.1:1"  # nothing listens here -> fallback

SAMPLE = {
    "name": "Summit Ridge Roofing",
    "category": "Roofing Contractor",
    "city": "Asheville, NC",
    "phone": "(828) 555-0147",
    "website": "https://summitridgeroofing.example",
    "reviews": [
        {"author": "Marcus D.", "rating": 5, "text": "Honest people, fixed our leak fast and cleaned up every nail."},
        {"author": "Priya S.", "rating": 5, "text": "Replaced our entire roof in two days with a clear, no-surprises estimate."},
        {"author": "Greg T.", "rating": 4, "text": "Good quality work on a tricky metal roof repair, fair price."},
    ],
}


def _content():
    b = ManualSource.from_dict(SAMPLE)
    return b, generate_site_content(b, endpoint=OFFLINE_ENDPOINT, timeout=2.0)


def test_render_produces_valid_looking_html():
    _b, content = _content()
    doc = render_html(content)
    assert doc.startswith("<!doctype html>")
    assert "<html lang=\"en\">" in doc
    assert doc.count("<main") == 1
    assert "Summit Ridge Roofing" in doc
    assert "style.css" in doc
    # No trackers / external scripts.
    assert "google-analytics" not in doc
    assert "<script src" not in doc


def test_fallback_used_when_llm_offline():
    _b, content = _content()
    assert content.provenance["copy_source"] == "fallback_template"
    # Still produces usable, non-empty copy.
    assert content.hero_headline
    assert len(content.services) >= 3


def test_testimonials_are_real_and_attributed():
    b, content = _content()
    real_texts = {r.text for r in b.reviews}
    real_authors = {r.author for r in b.reviews}
    assert 1 <= len(content.testimonials) <= 5
    for t in content.testimonials:
        # Author must be a real supplied author (never invented).
        assert t.author in real_authors
        # Text must be a verbatim prefix of a real review (modulo whitespace).
        matched = any(
            " ".join(r.text.split()).startswith(t.text.rstrip("…"))
            for r in b.reviews
        )
        assert matched, f"testimonial not traceable to a real review: {t.text!r}"
        assert t.author in real_authors


def test_provenance_lists_used_reviews():
    _b, content = _content()
    used = content.provenance["reviews_used_as_testimonials"]
    assert len(used) == len(content.testimonials)
    for entry in used:
        assert entry["source_index"] is not None


def test_write_site_creates_files(tmp_path):
    _b, content = _content()
    paths = write_site(content, str(tmp_path / "out"))
    for key in ("index", "css", "provenance"):
        assert os.path.exists(paths[key])
    html = open(paths["index"], encoding="utf-8").read()
    assert "reviewforge-provenance" in html
