"""Page-level honesty: footer wording, rating basis, legal pages, image labels,
image metadata, and the removal of the Google Places path."""
import os
import pathlib
import struct
import zlib

import pytest

from reviewforge import images as images_mod
from reviewforge.generator import ILLUSTRATIVE_DISCLOSURE, generate_site_content
from reviewforge.models import (
    ORIGIN_GENERATED,
    ORIGIN_SUPPLIED,
    LegalRequirementError,
    SiteImage,
)
from reviewforge.renderer import render_html
from reviewforge.sources import ManualSource

OFFLINE = "http://127.0.0.1:1"
ROOT = pathlib.Path(__file__).resolve().parent.parent

BASE = {
    "name": "Summit Ridge Roofing",
    "category": "Roofing Contractor",
    "city": "Asheville, NC",
    "phone": "(828) 555-0147",
    "reviews": [
        {"author": "Marcus D.", "rating": 5, "text": "Honest people, fixed our leak fast."},
        {"author": "Priya S.", "rating": 5, "text": "Replaced our entire roof in two days."},
        {"author": "Greg T.", "rating": 3, "text": "Good work on a tricky metal roof repair."},
    ],
}


def _page(**over):
    b = ManualSource.from_dict({**BASE, **over})
    content = generate_site_content(b, endpoint=OFFLINE, timeout=2.0)
    return content, render_html(content)


def _body(doc):
    return doc[doc.index("<body>"):]


# ---------------------------------------------------------------------------
# H4 footer wording + source_url
# ---------------------------------------------------------------------------
def test_footer_attributes_reviews_to_the_business_not_to_us():
    _c, doc = _page()
    assert ("Testimonials are reproduced verbatim from reviews supplied by "
            "Summit Ridge Roofing.") in doc
    assert "real, verbatim, and attributed" not in doc
    assert "Real reviews from real customers" not in doc


def test_review_source_url_is_recorded_and_linked():
    reviews = [dict(r) for r in BASE["reviews"]]
    reviews[0]["source_url"] = "https://reviews.example/r/1"
    content, doc = _page(reviews=reviews)
    used = {u["author"]: u for u in content.provenance["reviews_used_as_testimonials"]}
    assert used["Marcus D."]["source_url"] == "https://reviews.example/r/1"
    assert used["Priya S."]["source_url"] is None
    assert 'href="https://reviews.example/r/1"' in _body(doc)


# ---------------------------------------------------------------------------
# H5 rating basis
# ---------------------------------------------------------------------------
def test_without_summary_rating_is_the_average_of_reviews_shown():
    content, doc = _page()
    assert "average of the 3 reviews shown" in doc
    assert "4.3 out of 5" in doc
    assert content.provenance["rating_display"]["basis"].startswith("average of the reviews shown")


def test_rating_summary_is_shown_with_platform_and_count():
    content, doc = _page(rating_summary={"average": 4.6, "count": 40, "platform": "Google"})
    assert "4.6 on Google &middot; 40 reviews" in doc
    assert "reviews shown" not in _body(doc)
    assert content.provenance["rating_display"]["count"] == 40


@pytest.mark.parametrize("bad", [
    {"average": 4.6, "count": 40},
    {"average": 7, "count": 40, "platform": "Google"},
    {"average": 4.6, "count": 0, "platform": "Google"},
    "4.6",
])
def test_bad_rating_summary_rejected(bad):
    with pytest.raises(ValueError, match="rating_summary"):
        ManualSource.from_dict({**BASE, "rating_summary": bad})


# ---------------------------------------------------------------------------
# H7 legal pages
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("legal", [
    None,
    {"impressum": "Summit GmbH, Musterstr. 1, 10115 Berlin"},
    {"privacy": "https://example.com/datenschutz"},
])
def test_german_business_without_both_legal_pages_is_refused(legal):
    data = {**BASE, "country": "DE"}
    if legal is not None:
        data["legal"] = legal
    with pytest.raises(LegalRequirementError, match="Impressum"):
        ManualSource.from_dict(data)


def test_german_build_fails_through_the_cli(tmp_path, capsys):
    import json

    from reviewforge.cli import main

    src = tmp_path / "biz.json"
    src.write_text(json.dumps({**BASE, "country": "Germany"}), encoding="utf-8")
    rc = main(["build", "-i", str(src), "-o", str(tmp_path / "out"),
               "--endpoint", OFFLINE, "--images", "off"])
    assert rc == 2
    assert "Impressum" in capsys.readouterr().err
    assert not (tmp_path / "out" / "index.html").exists()


def test_german_business_with_legal_pages_renders_german_labels():
    content, doc = _page(country="DE", legal={
        "impressum": "Summit GmbH\nMusterstr. 1\n10115 Berlin",
        "privacy": "https://example.com/datenschutz",
    })
    body = _body(doc)
    assert '<a href="#legal-impressum">Impressum</a>' in body
    assert '<a href="https://example.com/datenschutz">Datenschutz</a>' in body
    assert 'id="legal-impressum"' in body and "Musterstr. 1" in body
    assert content.provenance["legal"]["warnings"] == []


def test_other_eu_country_warns_but_builds():
    content, doc = _page(country="FR")
    assert content.provenance["legal"]["warnings"]
    assert "FR" in content.provenance["legal"]["warnings"][0]


def test_non_eu_labels_and_no_warning():
    content, doc = _page(country="US", legal={"privacy": "https://example.com/privacy"})
    assert '<a href="https://example.com/privacy">Privacy</a>' in doc
    assert "Datenschutz" not in doc
    assert content.provenance["legal"]["warnings"] == []


def test_invalid_country_code_rejected():
    with pytest.raises(ValueError, match="country"):
        ManualSource.from_dict({**BASE, "country": "Narnia"})


# ---------------------------------------------------------------------------
# H6 illustrative images: flagged in markup, disclosed in the footer
# ---------------------------------------------------------------------------
def _illustrative_content():
    from reviewforge.generator import ImageSet, Service, SiteContent

    b = ManualSource.from_dict(BASE)
    hero = SiteImage(src="images/hero.png", origin=ORIGIN_GENERATED, role="hero",
                     width=1344, height=768)
    svc = SiteImage(src="images/service-1.png", origin=ORIGIN_GENERATED,
                    role="service", width=768, height=768)
    services = [Service("Roof Repair", "Leaks fixed.", image=svc),
                Service("Gutters", "Gutter work.")]
    return SiteContent(
        business=b, hero_headline="Roofing", hero_subhead="Roofing in Asheville.",
        services=services, about="About.", cta_label="Call for a quote",
        testimonials=[], images=ImageSet(hero=hero, service_images=[svc]),
        provenance={},
    )


def test_illustrative_images_are_flagged_and_disclosed_in_footer():
    doc = render_html(_illustrative_content())
    body = _body(doc)
    assert body.count('data-illustrative="true"') == 2
    # No on-image badge: the footer disclosure carries the label.
    assert "illus-badge" not in body
    assert "Illustrative image" not in body
    assert ILLUSTRATIVE_DISCLOSURE in body


def test_imageless_card_next_to_imaged_cards_gets_a_panel_not_a_gap():
    body = _body(render_html(_illustrative_content()))
    assert body.count('class="card-media blank"') == 1


def test_business_photos_get_credit_not_disclosure():
    from reviewforge.generator import ImageSet, SiteContent

    b = ManualSource.from_dict(BASE)
    hero = SiteImage(src="images/photo-1.jpg", origin=ORIGIN_SUPPLIED, role="hero",
                     attribution="Photo: A. Person, CC0")
    content = SiteContent(
        business=b, hero_headline="Roofing", hero_subhead="Roofing.",
        services=[], about="About.", cta_label="Call for a quote",
        testimonials=[], images=ImageSet(hero=hero), provenance={},
    )
    body = _body(render_html(content))
    assert "illus-badge" not in body
    assert "Photo: A. Person, CC0" in body


def test_photo_credit_css_is_legible():
    from reviewforge.renderer import STYLE_CSS

    rule = STYLE_CSS[STYLE_CSS.index(".photo-credit {"):]
    rule = rule[:rule.index("}")]
    assert "color: #fff" in rule and "rgba(8,20,32,0.82)" in rule
    assert "position: absolute" in rule
    assert "illus-badge" not in STYLE_CSS


# ---------------------------------------------------------------------------
# 8. Generated-image metadata is stripped
# ---------------------------------------------------------------------------
def _chunk(ctype: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + ctype + data
            + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))


def _png_with_text() -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00\x00")
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"tEXt", b'prompt\x00{"ckpt": "secret-model.safetensors"}')
            + _chunk(b"iTXt", b"workflow\x00\x00\x00\x00\x00{}")
            + _chunk(b"zTXt", b"Comment\x00\x00" + zlib.compress(b"hello"))
            + _chunk(b"IDAT", idat) + _chunk(b"IEND", b""))


def test_png_text_chunks_are_removed(tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(_png_with_text())
    removed = images_mod.strip_metadata(str(p))
    assert sorted(removed) == ["iTXt", "tEXt", "zTXt"]
    data = p.read_bytes()
    assert b"tEXt" not in data and b"iTXt" not in data and b"zTXt" not in data
    assert b"secret-model" not in data
    assert b"IHDR" in data and b"IDAT" in data and data.endswith(_chunk(b"IEND", b""))
    assert images_mod.probe_image_size(str(p)) == (1, 1)


def test_jpeg_exif_xmp_and_comments_are_removed(tmp_path):
    soi, eoi = b"\xff\xd8", b"\xff\xd9"

    def seg(marker, payload):
        return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload

    app0 = seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    exif = seg(0xE1, b"Exif\x00\x00GPS-SECRET")
    xmp = seg(0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x>secret</x>")
    com = seg(0xFE, b"made by some tool")
    sof = seg(0xC0, b"\x08\x00\x02\x00\x03\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01")
    sos = b"\xff\xda" + struct.pack(">H", 12) + b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    p = tmp_path / "x.jpg"
    p.write_bytes(soi + app0 + exif + xmp + com + sof + sos + b"\x12\x34" + eoi)
    removed = images_mod.strip_metadata(str(p))
    assert removed == ["APP1", "APP1", "COM"]
    data = p.read_bytes()
    assert b"GPS-SECRET" not in data and b"secret" not in data and b"some tool" not in data
    assert b"JFIF" in data
    assert images_mod.probe_image_size(str(p)) == (3, 2)


def test_generated_images_are_written_without_metadata(tmp_path):
    class TextEmbeddingBackend(images_mod.ImageBackend):
        name = "fake"

        def render(self, plan, out_path, seed):
            pathlib.Path(out_path).write_bytes(_png_with_text())
            return {"backend": self.name, "seed": seed}

    imgs, failures = images_mod.generate_illustrative_images(
        "Roofing", str(tmp_path), backend=TextEmbeddingBackend(), service_count=1)
    assert not failures and len(imgs) == 2
    for img in imgs:
        data = (tmp_path / os.path.basename(img.src)).read_bytes()
        assert b"tEXt" not in data and b"secret-model" not in data
        assert sorted(img.generation["embedded_metadata_removed"]) == ["iTXt", "tEXt", "zTXt"]


def test_staged_supplied_photos_are_stripped_too(tmp_path):
    src = tmp_path / "in.png"
    src.write_bytes(_png_with_text())
    img = SiteImage(src=str(src), origin=ORIGIN_SUPPLIED)
    staged = images_mod.stage_supplied_photos([img], str(tmp_path / "out"))
    data = (tmp_path / "out" / os.path.basename(staged[0].src)).read_bytes()
    assert b"tEXt" not in data


# ---------------------------------------------------------------------------
# H3 the Google Places path is gone
# ---------------------------------------------------------------------------
def test_google_places_code_is_gone():
    from reviewforge import models, sources

    assert not hasattr(sources, "GooglePlacesSource")
    assert not hasattr(models, "ORIGIN_PLACES")
    assert models.VALID_ORIGINS == ("supplied", "generated")
    with pytest.raises(ValueError, match="origin"):
        SiteImage(src="x.png", origin="places")


def test_no_places_endpoints_or_key_in_url_paths_in_the_package():
    offenders = []
    for path in (ROOT / "reviewforge").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in ("maps.googleapis.com", "places.googleapis.com",
                       "GOOGLE_PLACES_API_KEY", "photo_reference", "?key=", "&key=",
                       "\"key\":"):
            if needle in text:
                offenders.append(f"{path.name}: {needle}")
    assert offenders == []


def test_readme_does_not_offer_a_places_path():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "GOOGLE_PLACES_API_KEY" not in readme
    assert "GooglePlacesSource" not in readme
    assert "photo_reference" not in readme
