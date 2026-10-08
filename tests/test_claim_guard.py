"""The copy can only claim what the business actually told us.

The system prompt forbids inventing credentials; a 7B model wrote "With over 20
years of experience" for a business whose input says nothing about its age. A
prompt is not a control, so the output is audited, retried once with the
rejected phrases fed back, and otherwise replaced by the deterministic
template -- which must itself pass the same audit.
"""
import pytest

from reviewforge.generator import (
    Service,
    _fallback_content,
    _fallback_as_copy,
    _supporting_corpus,
    audit_copy,
    generate_site_content,
    unsupported_claims,
)
from reviewforge.renderer import render_html
from reviewforge.sources import ManualSource

BASE = {
    "name": "Summit Ridge Roofing",
    "category": "Roofing Contractor",
    "city": "Asheville, NC",
    "phone": "(828) 555-0147",
    "reviews": [
        {"author": "Marcus D.", "rating": 5, "text": "Honest people, fixed our leak fast."},
        {"author": "Priya S.", "rating": 5, "text": "Replaced our entire roof in two days."},
        {"author": "Greg T.", "rating": 4, "text": "Good work on a tricky metal roof repair."},
    ],
}

CLEAN_COPY = {
    "hero_headline": "Roof Repairs and Replacements",
    "hero_subhead": "Roof repair and replacement for homes in Asheville, NC.",
    "about": "Summit Ridge Roofing is a roofing contractor serving "
             "Asheville. Customers mention its honesty and clean-up.",
    "cta_label": "Call for a quote",
    "services": [Service("Roof Repair", "Leaks found and fixed.")],
}


def _business(**over):
    return ManualSource.from_dict({**BASE, **over})


def _copy(**over):
    return {**CLEAN_COPY, **over}


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,kind",
    [
        ("With over 20 years of experience serving Asheville.", "years in business"),
        ("Decades of roofing know-how.", "years in business"),
        ("Serving the mountains since 1998.", "founding year"),
        ("Fully licensed and insured roofing specialists.", "licensing/certification"),
        ("Bonded crews on every job.", "licensing/certification"),
        ("OSHA-compliant job sites.", "licensing/certification"),
        ("An A+ rating with the BBB.", "rating-agency claim"),
        ("Accredited by the Better Business Bureau.", "rating-agency claim"),
        ("An award-winning contractor.", "award/ranking"),
        ("Voted best in Asheville three times.", "award/ranking"),
        ("The best roofers around.", "award/ranking"),
        ("Asheville's top-rated roofer.", "award/ranking"),
        ("The highest rated crew in town.", "award/ranking"),
        ("A leading roofing company.", "award/ranking"),
        ("Premier roofing services.", "award/ranking"),
        ("Expert roof repair.", "expertise claim"),
        ("Our experts will help.", "expertise claim"),
        ("Experienced roofers.", "expertise claim"),
        ("Professional service every time.", "expertise claim"),
        ("Trained professionals.", "expertise claim"),
        ("Your trusted local roofer.", "reputation claim"),
        ("Reliable roof repair.", "reputation claim"),
        ("Dependable service.", "reputation claim"),
        ("High-quality materials.", "reputation claim"),
        ("Affordable roofing.", "price claim"),
        ("Available 24/7.", "availability claim"),
        ("Emergency leak repair.", "availability claim"),
        ("Same-day service.", "availability claim"),
        ("A family-owned business.", "ownership claim"),
        ("Locally owned and operated.", "ownership claim"),
        ("Veteran-owned roofing.", "ownership claim"),
        ("A woman-owned company.", "ownership claim"),
        ("Third-generation roofers.", "ownership claim"),
        ("Eco-friendly materials.", "environmental claim"),
        ("The lowest prices in town.", "price claim"),
        ("We price match any written quote.", "price claim"),
        ("We complete 98% of jobs in a single day.", "statistic"),
        ("Hundreds of happy homeowners.", "volume claim"),
        ("Thousands of roofs.", "volume claim"),
        ("Dozens of repairs a month.", "volume claim"),
        ("Over 2000 roofs installed.", "volume statistic"),
        ("1,500 homes served.", "volume statistic"),
        ("Rated 4.9 stars.", "rating claim"),
        ("All work carries a lifetime warranty.", "guarantee/warranty"),
        ("Lifetime protection.", "guarantee/warranty"),
        ("Our workmanship is guaranteed.", "guarantee/warranty"),
        ("Call for a free quote.", "free offer"),
        ("Free estimates on all jobs.", "free offer"),
    ],
)
def test_unsupported_claims_are_detected(text, kind):
    found = unsupported_claims(text, corpus="")
    assert found, f"missed an invented claim: {text!r}"
    assert any(f["kind"] == kind for f in found), [f["kind"] for f in found]


@pytest.mark.parametrize(
    "text",
    [
        "Roofing contractor serving Asheville, NC.",
        "Call for a quote on your roof.",
        "Careful work, described by customers in their own words.",
        "Repairs, replacements and gutter work across the Asheville area.",
    ],
)
def test_ordinary_copy_is_not_flagged(text):
    assert unsupported_claims(text, corpus="") == []


def test_a_claim_the_reviews_support_is_allowed():
    """If a customer wrote it, the copy may repeat it."""
    b = _business(reviews=[
        {"author": "A", "rating": 5,
         "text": "They have been roofing here for 30 years and it shows. "
                 "The most experienced crew we called, and they came out for "
                 "an emergency on a Sunday."},
    ])
    corpus = _supporting_corpus(b)
    assert unsupported_claims("Roofing Asheville for 30 years.", corpus) == []
    assert unsupported_claims("An experienced crew for emergency repairs.", corpus) == []
    # A different, unsupported number is still caught.
    assert unsupported_claims("Roofing Asheville for 45 years.", corpus)
    # ...and an unrelated puffery word too.
    assert unsupported_claims("The best crew.", corpus)


# ---------------------------------------------------------------------------
# "Free" is opt-in, never inferred
# ---------------------------------------------------------------------------
def test_free_is_rejected_unless_the_business_opts_in():
    plain = _business()
    assert plain.offers_free_estimates is False
    problems = audit_copy(_copy(cta_label="Call for a free quote"), plain)
    assert [p["kind"] for p in problems] == ["free offer"]

    opted_in = _business(offers_free_estimates=True)
    assert audit_copy(_copy(cta_label="Call for a free quote"), opted_in) == []


def test_a_review_mentioning_free_does_not_license_a_free_offer():
    b = _business(reviews=[
        {"author": "A", "rating": 5, "text": "They gave me a free estimate, great."},
    ])
    assert audit_copy(_copy(cta_label="Free estimates"), b)


@pytest.mark.parametrize("free", [False, True])
def test_fallback_mentions_free_only_when_opted_in(free):
    b = _business(offers_free_estimates=free)
    content = generate_site_content(b, endpoint="http://127.0.0.1:1", timeout=2.0)
    assert content.provenance["copy_source"] == "fallback_template"
    body = render_html(content)
    body = body[body.index("<body>"):]
    assert ("free" in body.lower()) is free
    if not free:
        assert content.cta_label == "Call for a quote"


def test_prompt_only_seeds_free_when_opted_in():
    from reviewforge.generator import _build_prompt

    no = _build_prompt(_business())
    assert "free quote" not in no.lower() and "free estimate" not in no.lower()
    assert "Do NOT use the word 'free'" in no
    yes = _build_prompt(_business(offers_free_estimates=True))
    assert "free estimate" in yes.lower()


def test_offers_free_estimates_must_be_boolean():
    with pytest.raises(ValueError, match="offers_free_estimates"):
        _business(offers_free_estimates="yes")


# ---------------------------------------------------------------------------
# Field coverage
# ---------------------------------------------------------------------------
def test_audit_copy_checks_every_field():
    copy = {
        "hero_headline": "Award-winning Roofing",
        "hero_subhead": "Serving Asheville since 1998.",
        "about": "A family-owned roofer.",
        "cta_label": "Call for a free quote",
        "services": [Service("Roof Repair", "Fully insured crews.")],
    }
    problems = audit_copy(copy, _business())
    fields = {p["field"] for p in problems}
    assert fields == {"hero_headline", "hero_subhead", "about", "cta_label",
                      "service:Roof Repair"}


# ---------------------------------------------------------------------------
# The deterministic fallback must pass its own audit
# ---------------------------------------------------------------------------
CATEGORIES = [
    ("Roofing Contractor", "Asheville, NC"),
    ("Plumber", "Boise, ID"),
    ("Electrician", "Leipzig"),
    ("HVAC Contractor", "Tulsa, OK"),
    ("Landscaping", "Bristol"),
    ("House Painter", "Graz"),
    ("Cleaning Service", "Austin, TX"),
    ("Auto Repair Shop", "Dayton, OH"),
    ("Locksmith", "Cork"),
]


@pytest.mark.parametrize("category,city", CATEGORIES)
@pytest.mark.parametrize("free", [False, True])
@pytest.mark.parametrize("hours", [None, "Mon-Fri 8am-5pm"])
def test_fallback_passes_the_audit(category, city, free, hours):
    data = {**BASE, "category": category, "city": city,
            "name": f"Example {category}", "offers_free_estimates": free}
    if hours:
        data["hours"] = hours
    b = ManualSource.from_dict(data)
    copy = _fallback_as_copy(b)
    assert audit_copy(copy, b) == [], audit_copy(copy, b)
    headline, subhead, services, about, cta = _fallback_content(b)
    assert headline and subhead and about and cta
    assert len(services) == 3


def test_fallback_uses_the_right_article():
    b = ManualSource.from_dict({**BASE, "category": "Electrician"})
    _h, subhead, *_ = _fallback_content(b)
    assert "is an electrician" in subhead


# ---------------------------------------------------------------------------
# Retry once with the rejected phrases, then fall back
# ---------------------------------------------------------------------------
def _scripted(monkeypatch, drafts):
    """Make _generate_copy return each draft in turn; record the calls."""
    from reviewforge import generator as gen

    calls = []

    def fake(business, model, endpoint, timeout, rejected=None):
        calls.append(rejected)
        draft = drafts[len(calls) - 1]
        if draft is None:
            return None, False, "LLM unavailable"
        return dict(draft), True, "copy generated by test-model"

    monkeypatch.setattr(gen, "_generate_copy", fake)
    return calls


def test_rejected_draft_is_retried_with_feedback_and_clean_retry_is_kept(monkeypatch):
    bad = _copy(hero_headline="Expert Roofing", about="Over 20 years in Asheville.")
    calls = _scripted(monkeypatch, [bad, CLEAN_COPY])
    content = generate_site_content(_business())
    assert len(calls) == 2
    assert calls[0] is None
    assert set(calls[1]) == {"Expert", "Over 20 years"}
    prov = content.provenance
    assert prov["copy_source"] == "llm"
    assert content.hero_headline == CLEAN_COPY["hero_headline"]
    assert [a["attempt"] for a in prov["copy_attempts"]] == [1, 2]
    assert prov["copy_attempts"][1]["rejected_claims"] == []
    assert {c["claim"] for c in prov["rejected_claims"]} == {"Expert", "Over 20 years"}
    assert "second draft passed" in prov["note"]


def test_retry_that_still_overclaims_falls_back(monkeypatch):
    bad = _copy(about="With over 20 years of experience, we specialize in roofing.")
    worse = _copy(hero_headline="Asheville's Best Roofer")
    calls = _scripted(monkeypatch, [bad, worse])
    content = generate_site_content(_business())
    assert len(calls) == 2
    prov = content.provenance
    assert prov["copy_source"] == "fallback_template"
    assert prov["llm_model"] is None
    assert "20 years" in prov["note"]
    assert {c["attempt"] for c in prov["rejected_claims"]} == {1, 2}
    # The lie is not on the visible page; it survives only in the embedded
    # provenance record, which is the point: the audit says what was thrown
    # away and why.
    doc = render_html(content)
    body = doc[doc.index("<body>"):]
    assert "20 years" not in body and "Best Roofer" not in body
    assert "20 years" in doc


def test_retry_unavailable_falls_back(monkeypatch):
    calls = _scripted(monkeypatch, [_copy(hero_headline="Trusted Roofing"), None])
    content = generate_site_content(_business())
    assert len(calls) == 2
    assert content.provenance["copy_source"] == "fallback_template"


def test_clean_first_draft_is_kept_without_retry(monkeypatch):
    calls = _scripted(monkeypatch, [CLEAN_COPY])
    content = generate_site_content(_business())
    assert len(calls) == 1
    assert content.provenance["copy_source"] == "llm"
    assert content.provenance["rejected_claims"] == []
    assert content.hero_headline == CLEAN_COPY["hero_headline"]


def test_retry_prompt_names_the_rejected_phrases():
    from reviewforge.generator import _build_prompt

    prompt = _build_prompt(_business(), rejected=["Expert", "24/7"])
    assert "previous draft was rejected" in prompt
    assert "'Expert'" in prompt and "'24/7'" in prompt


def test_llm_endpoint_address_is_not_published(monkeypatch):
    _scripted(monkeypatch, [CLEAN_COPY])
    content = generate_site_content(_business(), endpoint="http://203.0.113.7:11434")
    assert "203.0.113.7" not in render_html(content)
    assert content.provenance["llm_endpoint"].startswith("non-local")


def test_support_allows_simple_plural_and_singular_only():
    corpus = "mon-fri 7am-5pm, 24/7 emergency call-out. the experts arrived."
    assert unsupported_claims("We handle emergencies.", corpus) == []
    assert unsupported_claims("An expert repair.", corpus) == []
    # Whole words only: "expert" inside "expertise" does not count.
    assert unsupported_claims("Real expertise.", "expertly done") != []
