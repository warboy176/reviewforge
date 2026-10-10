"""Tests for the image layer and its honesty guarantees.

The rules under test are the ones that matter if a real small business puts
this page on the internet:

  * imagery the business did not supply can never be flagged as its own;
  * a caption claiming ownership on illustrative imagery is stripped, not
    rendered;
  * illustrative imagery never reaches the "our work" gallery;
  * every image is recorded in provenance.json with its origin;
  * a missing real photo is an error, never silently replaced;
  * no logo is ever generated.

Nothing here touches the network: generation is exercised through a fake
backend that writes a 1x1 PNG.
"""
import base64
import json
import os

import pytest

from reviewforge import images as images_mod
from reviewforge.generator import (
    ILLUSTRATIVE_DISCLOSURE,
    ImageConfig,
    generate_site_content,
    resolve_images,
)
from reviewforge.models import (
    GENERIC_ILLUSTRATIVE_ALT,
    ORIGIN_GENERATED,
    ORIGIN_SUPPLIED,
    SiteImage,
    caption_implies_ownership,
)
from reviewforge.renderer import render_html
from reviewforge.sources import ManualSource

OFFLINE_ENDPOINT = "http://127.0.0.1:1"  # nothing listens here -> copy fallback

# Smallest valid PNG (1x1, transparent).
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/x8AAwMB/6gBnQAAAABJRU5ErkJggg=="
)

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


class FakeBackend(images_mod.ImageBackend):
    """Writes a real (tiny) PNG without touching a GPU or the network."""

    name = "fake"

    def __init__(self, fail_slugs=()):
        self.fail_slugs = set(fail_slugs)
        self.calls = []

    def health(self):
        return {"backend": self.name}

    def render(self, plan, out_path, seed):
        self.calls.append((plan.slug, plan.prompt, seed))
        if plan.slug in self.fail_slugs:
            raise images_mod.ImageBackendUnavailable("fake failure")
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "wb") as fh:
            fh.write(_PNG_1x1)
        return {"backend": self.name, "prompt": plan.prompt, "seed": seed}


# ---------------------------------------------------------------------------
# SiteImage honesty enforcement
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "caption",
    [
        "Our work on a recent roof",
        "A recent job in West Asheville",
        "A project we completed last spring",
        "One of our crew on site",
        "Before and after",
        "This home needed a full tear-off",
        "From our portfolio",
        "A customer's roof we re-shingled",
        "Actual job photo",
    ],
)
def test_illustrative_caption_claiming_ownership_is_rejected(caption):
    img = SiteImage(src="images/hero.png", alt="A roofline", caption=caption,
                    origin=ORIGIN_GENERATED, role="hero")
    assert img.caption is None, "ownership-claiming caption survived on an illustrative image"
    assert img.rejected_caption == caption
    assert "illustrative" in img.to_provenance()["rejected_caption_reason"]


def test_illustrative_neutral_caption_is_kept():
    img = SiteImage(src="images/hero.png", alt="A roofline",
                    caption="Asphalt shingles in close detail",
                    origin=ORIGIN_GENERATED)
    assert img.caption == "Asphalt shingles in close detail"
    assert img.rejected_caption is None


def test_illustrative_alt_claiming_ownership_is_replaced_with_generic():
    img = SiteImage(src="images/hero.png", alt="Our crew finishing a roof",
                    origin=ORIGIN_GENERATED)
    assert img.alt == GENERIC_ILLUSTRATIVE_ALT
    assert img.rejected_alt == "Our crew finishing a roof"


def test_illustrative_image_with_no_alt_gets_generic_alt():
    img = SiteImage(src="images/hero.png", origin=ORIGIN_GENERATED)
    assert img.alt == GENERIC_ILLUSTRATIVE_ALT


def test_supplied_photo_keeps_its_ownership_caption():
    """The business is entitled to say "our work" about its own photo."""
    img = SiteImage(src="photos/roof.jpg", alt="New shingles",
                    caption="A full tear-off we completed in West Asheville",
                    origin=ORIGIN_SUPPLIED)
    assert img.is_business_own is True
    assert img.caption == "A full tear-off we completed in West Asheville"
    assert img.rejected_caption is None


def test_is_business_own_is_derived_and_cannot_be_forged():
    """Passing is_business_own=True on a generated image must not stick."""
    img = SiteImage(src="images/hero.png", origin=ORIGIN_GENERATED,
                    is_business_own=True)
    assert img.is_business_own is False
    assert img.illustrative is True


def test_invalid_origin_rejected():
    with pytest.raises(ValueError, match="origin"):
        SiteImage(src="x.png", origin="scraped")


def test_caption_implies_ownership_is_not_trigger_happy_about_plain_nouns():
    assert caption_implies_ownership("Asphalt shingles and a nail gun") is False
    assert caption_implies_ownership("A standing seam metal roof") is False
    assert caption_implies_ownership("our new roof") is True


# ---------------------------------------------------------------------------
# Supplied-photo path
# ---------------------------------------------------------------------------
def _write_photo(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(_PNG_1x1)
    return str(p)


def test_supplied_photos_make_hero_and_gallery(tmp_path):
    data = {
        **BASE,
        "photos": [
            {"src": _write_photo(tmp_path, "a.png"), "alt": "New shingles",
             "caption": "Full re-shingle we completed in Asheville"},
            {"src": _write_photo(tmp_path, "b.png"), "alt": "Ridge detail"},
            {"src": _write_photo(tmp_path, "c.png"), "alt": "Gutter run"},
        ],
    }
    b = ManualSource.from_dict(data)
    out = str(tmp_path / "out")
    content = generate_site_content(
        b, endpoint=OFFLINE_ENDPOINT, timeout=2.0, out_dir=out,
        image_config=ImageConfig(mode="auto"),
    )
    iset = content.images
    assert iset.hero is not None and iset.hero.is_business_own
    assert len(iset.gallery) == 2
    assert all(p.is_business_own for p in iset.gallery)
    # Not illustrative -> no footer disclosure.
    assert iset.uses_illustrative is False
    # Files were staged next to the page, and src rewritten to a relative path.
    assert iset.hero.src.startswith("images/")
    assert os.path.exists(os.path.join(out, iset.hero.src))
    # Dimensions probed so the page does not shift as photos load.
    assert iset.hero.width == 1 and iset.hero.height == 1

    doc = render_html(content)
    assert 'id="work"' in doc
    assert "Our work" in doc
    assert "Full re-shingle we completed in Asheville" in doc
    assert ILLUSTRATIVE_DISCLOSURE not in doc
    assert 'data-illustrative="true"' not in doc


def test_supplied_photos_win_over_generation_in_auto_mode(tmp_path):
    data = {**BASE, "photos": [{"src": _write_photo(tmp_path, "a.png"), "alt": "Roof"}]}
    b = ManualSource.from_dict(data)
    iset = resolve_images(
        b, str(tmp_path / "out"), ImageConfig(mode="auto", backend="comfyui",
                                              comfyui_url="http://127.0.0.1:1")
    )
    assert iset.info["source"] == "business-supplied photos"
    # A single photo besides... none: no gallery from one photo.
    assert iset.gallery == []
    assert "image_backend" not in iset.info, "auto mode must not call a backend when photos exist"


def test_missing_supplied_photo_is_an_error_not_a_substitution(tmp_path):
    data = {**BASE, "photos": [{"src": str(tmp_path / "nope.jpg"), "alt": "Roof"}]}
    b = ManualSource.from_dict(data)
    with pytest.raises(FileNotFoundError, match="will not substitute"):
        resolve_images(b, str(tmp_path / "out"), ImageConfig(mode="auto"))


def test_photo_without_src_rejected():
    with pytest.raises(ValueError, match="missing 'src'"):
        ManualSource.from_dict({**BASE, "photos": [{"alt": "no source"}]})


def test_own_only_mode_never_generates(tmp_path):
    b = ManualSource.from_dict(BASE)  # no photos
    iset = resolve_images(b, str(tmp_path / "out"), ImageConfig(mode="own-only"))
    assert iset.has_images is False
    assert "own-only" in iset.info["note"]


def test_images_off_mode(tmp_path):
    b = ManualSource.from_dict(BASE)
    iset = resolve_images(b, str(tmp_path / "out"), ImageConfig(mode="off"))
    assert iset.has_images is False
    assert iset.info["mode"] == "off"


# ---------------------------------------------------------------------------
# Illustrative generation path
# ---------------------------------------------------------------------------
def test_generated_images_are_illustrative_uncaptioned_and_ungalleried(tmp_path):
    backend = FakeBackend()
    imgs, failures = images_mod.generate_illustrative_images(
        "Roofing Contractor", str(tmp_path / "out" / "images"), backend=backend,
        service_count=3, seed=7,
    )
    assert failures == []
    assert len(imgs) == 4  # hero + 3 service
    assert [i.role for i in imgs][0] == "hero"
    for img in imgs:
        assert img.origin == ORIGIN_GENERATED
        assert img.is_business_own is False
        assert img.illustrative is True
        assert img.caption is None
        assert img.alt
        assert not caption_implies_ownership(img.alt)
        assert os.path.exists(os.path.join(tmp_path, "out", img.src))
    # Prompts must forbid text, logos and identifying detail.
    for _slug, prompt, _seed in backend.calls:
        assert "no text" in prompt
        assert "unbranded" in prompt or "no signage" in prompt


def test_roofing_scenes_selected_for_a_roofer():
    assert images_mod.scene_key_for_category("Roofing Contractor") == "roofing"
    assert images_mod.scene_key_for_category("Emergency Plumber") == "plumbing"
    assert images_mod.scene_key_for_category("Alpaca Grooming") == "generic"


def test_negative_prompt_blocks_identifying_content():
    for banned in ("text", "logo", "signage", "house number", "address",
                   "license plate", "recognisable face"):
        assert banned in images_mod.NEGATIVE_PROMPT


def test_illustrative_build_discloses_and_keeps_gallery_empty(tmp_path, monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(
        images_mod, "resolve_backend",
        lambda *a, **k: (backend, {"selected": "fake", "attempts": []}),
    )
    b = ManualSource.from_dict(BASE)
    out = str(tmp_path / "out")
    content = generate_site_content(
        b, endpoint=OFFLINE_ENDPOINT, timeout=2.0, out_dir=out,
        image_config=ImageConfig(mode="illustrative"),
    )
    iset = content.images
    assert iset.hero is not None and iset.hero.illustrative
    assert iset.service_images, "service cards should get illustrative imagery"
    assert iset.gallery == [], "illustrative imagery must never form a gallery"
    assert iset.uses_illustrative is True

    doc = render_html(content)
    assert ILLUSTRATIVE_DISCLOSURE in doc, "footer disclosure missing"
    assert 'data-illustrative="true"' in doc
    assert 'id="work"' not in doc, "no gallery section for illustrative imagery"
    assert "not photographs of" in doc  # inline note on the services section
    # Hero is above the fold: eager, everything else lazy.
    assert 'loading="eager"' in doc
    assert 'loading="lazy"' in doc
    # No trackers / JS sneaked in with the image layer.
    assert "<script src" not in doc
    assert "googletagmanager" not in doc


def test_partial_generation_failure_is_recorded_not_fatal(tmp_path, monkeypatch):
    backend = FakeBackend(fail_slugs={"service-2"})
    monkeypatch.setattr(
        images_mod, "resolve_backend",
        lambda *a, **k: (backend, {"selected": "fake", "attempts": []}),
    )
    b = ManualSource.from_dict(BASE)
    content = generate_site_content(
        b, endpoint=OFFLINE_ENDPOINT, timeout=2.0, out_dir=str(tmp_path / "out"),
        image_config=ImageConfig(mode="illustrative"),
    )
    failures = content.provenance["image_resolution"]["generation_failures"]
    assert [f["slug"] for f in failures] == ["service-2"]
    assert content.images.hero is not None


def test_no_backend_means_no_imagery_not_a_fake_one(tmp_path, monkeypatch):
    monkeypatch.setattr(
        images_mod, "resolve_backend",
        lambda *a, **k: (None, {"selected": None, "attempts": [
            {"backend": "comfyui", "ok": False, "error": "refused"}]}),
    )
    b = ManualSource.from_dict(BASE)
    content = generate_site_content(
        b, endpoint=OFFLINE_ENDPOINT, timeout=2.0, out_dir=str(tmp_path / "out"),
        image_config=ImageConfig(mode="illustrative"),
    )
    assert content.images.has_images is False
    assert content.provenance["uses_illustrative_imagery"] is False
    assert "text-only" in content.provenance["image_resolution"]["note"]


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
def test_provenance_records_every_image_with_origin(tmp_path, monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(
        images_mod, "resolve_backend",
        lambda *a, **k: (backend, {"selected": "fake", "attempts": []}),
    )
    b = ManualSource.from_dict(BASE)
    out = str(tmp_path / "out")
    content = generate_site_content(
        b, endpoint=OFFLINE_ENDPOINT, timeout=2.0, out_dir=out,
        image_config=ImageConfig(mode="illustrative"),
    )
    from reviewforge.renderer import write_site

    paths = write_site(content, out)
    prov = json.loads(open(paths["provenance"], encoding="utf-8").read())

    assert prov["uses_illustrative_imagery"] is True
    assert prov["illustrative_disclosure"] == ILLUSTRATIVE_DISCLOSURE
    assert len(prov["images"]) == len(content.images.all_images)
    srcs = {rec["src"] for rec in prov["images"]}
    assert srcs == {img.src for img in content.images.all_images}
    for rec in prov["images"]:
        assert rec["origin"] in ("supplied", "generated")
        assert "is_business_own" in rec and "illustrative" in rec
        assert rec["illustrative"] is True
        assert rec["caption"] is None
        # Generation detail must be traceable back to a prompt.
        assert rec["generation"]["prompt"]
    assert prov["image_resolution"]["scene_set"] == "roofing"


def test_provenance_records_a_stripped_caption(tmp_path):
    """A rejected caption is not just dropped -- it is reported."""
    data = {
        **BASE,
        "photos": [{"src": _write_photo(tmp_path, "a.png"), "alt": "Roof"}],
    }
    b = ManualSource.from_dict(data)
    # Force the hero to be illustrative-with-a-bad-caption by constructing it
    # directly, which is the only route a caller could try.
    bad = SiteImage(src="images/hero.png", alt="A roofline",
                    caption="A roof we installed last month",
                    origin=ORIGIN_GENERATED, role="hero")
    rec = bad.to_provenance()
    assert rec["illustrative"] is True
    assert rec["rejected_caption"] == "A roof we installed last month"
    assert rec["caption"] is None
    assert b.name  # sanity


def test_provenance_notes_supplied_photo_count(tmp_path):
    data = {**BASE, "photos": [
        {"src": _write_photo(tmp_path, "a.png"), "alt": "One"},
        {"src": _write_photo(tmp_path, "b.png"), "alt": "Two"},
    ]}
    b = ManualSource.from_dict(data)
    content = generate_site_content(
        b, endpoint=OFFLINE_ENDPOINT, timeout=2.0,
        out_dir=str(tmp_path / "out"), image_config=ImageConfig(mode="auto"),
    )
    assert content.provenance["photos_supplied"] == 2
    assert all(rec["is_business_own"] for rec in content.provenance["images"])
    assert content.provenance["illustrative_disclosure"] is None


# ---------------------------------------------------------------------------
# Logo
# ---------------------------------------------------------------------------
def test_no_logo_means_typographic_wordmark_not_a_generated_mark(tmp_path):
    b = ManualSource.from_dict(BASE)
    content = generate_site_content(b, endpoint=OFFLINE_ENDPOINT, timeout=2.0)
    assert content.images.logo is None
    assert "never generates a logo" in content.provenance["image_resolution"]["logo"]
    doc = render_html(content, theme="classic")
    assert 'class="brand wordmark"' in doc
    assert "<span class=\"mono\" aria-hidden=\"true\">SR</span>" in doc


def test_supplied_logo_is_used(tmp_path):
    data = {**BASE, "logo": {"src": _write_photo(tmp_path, "logo.png"),
                             "alt": "Summit Ridge Roofing logo"}}
    b = ManualSource.from_dict(data)
    assert b.logo is not None and b.logo.role == "logo"
    out = str(tmp_path / "out")
    content = generate_site_content(
        b, endpoint=OFFLINE_ENDPOINT, timeout=2.0,
        out_dir=out, image_config=ImageConfig(mode="own-only"),
    )
    assert content.images.logo is not None
    # Staged under its own name so it cannot collide with photo-N.
    assert content.images.logo.src == "images/logo-1.png"
    assert os.path.exists(os.path.join(out, "images", "logo-1.png"))
    doc = render_html(content)
    assert 'class="logo"' in doc
    assert 'class="mono"' not in doc  # wordmark replaced by the real logo


def test_image_generation_plans_never_include_a_logo():
    roles = {p.role for p in images_mod.plan_illustrative_images("Roofing Contractor")}
    assert roles == {"hero", "service"}
    assert "logo" not in roles


# ---------------------------------------------------------------------------
# Remote photos are referenced, never fetched and re-hosted
# ---------------------------------------------------------------------------
def test_remote_photo_urls_are_not_downloaded(tmp_path):
    img = SiteImage(src="https://example.com/job.jpg", origin=ORIGIN_SUPPLIED)
    staged = images_mod.stage_supplied_photos([img], str(tmp_path / "images"))
    assert staged[0].src == "https://example.com/job.jpg"
    assert not os.listdir(tmp_path / "images")


# ---------------------------------------------------------------------------
# Service-card image matching
# ---------------------------------------------------------------------------
def test_service_images_match_the_service_they_depict():
    """Positional assignment put a gutter photo on 'Siding Repair'."""
    from reviewforge.generator import Service, _assign_service_images

    services = [
        Service("Roof Repair", "Expert repairs for all types of roofs"),
        Service("Gutter Installation", "Custom gutter solutions for your home"),
        Service("Metal Roofing", "Expert metal roofing repairs and installations"),
    ]
    pool = [
        SiteImage(src="images/a.png", alt="Close detail of a standing seam metal roof",
                  origin=ORIGIN_GENERATED, role="service"),
        SiteImage(src="images/b.png", alt="A newly installed gutter and downspout",
                  origin=ORIGIN_GENERATED, role="service"),
        SiteImage(src="images/c.png", alt="Roofing tools laid out on roof decking",
                  origin=ORIGIN_GENERATED, role="service"),
    ]
    _assign_service_images(services, pool)
    assert services[1].image.src == "images/b.png"  # gutter -> Gutter Installation
    assert services[2].image.src == "images/a.png"  # metal  -> Metal Roofing
    assert services[0].image.src == "images/c.png"  # tools  -> leftover


def test_unmatchable_images_still_fill_cards_in_order():
    from reviewforge.generator import Service, _assign_service_images

    services = [Service("Alpha", ""), Service("Beta", "")]
    pool = [
        SiteImage(src="images/1.png", alt="Professional hand tools on a workbench",
                  origin=ORIGIN_GENERATED, role="service"),
        SiteImage(src="images/2.png", alt="A tidy workshop wall",
                  origin=ORIGIN_GENERATED, role="service"),
    ]
    _assign_service_images(services, pool)
    assert [s.image.src for s in services] == ["images/1.png", "images/2.png"]


def test_fewer_images_than_services_leaves_cards_text_only():
    from reviewforge.generator import Service, _assign_service_images

    services = [Service("Roof Repair", ""), Service("Gutter Installation", ""),
                Service("Siding", "")]
    pool = [SiteImage(src="images/g.png", alt="A newly installed gutter and downspout",
                      origin=ORIGIN_GENERATED, role="service")]
    _assign_service_images(services, pool)
    assert services[1].image is not None
    assert services[0].image is None and services[2].image is None
