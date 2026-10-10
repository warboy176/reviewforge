import html
import json
import pytest

from reviewforge.generator import ILLUSTRATIVE_DISCLOSURE, ImageSet, Service, SiteContent, generate_site_content
from reviewforge.models import ORIGIN_GENERATED, ORIGIN_SUPPLIED, SiteImage
from reviewforge import renderer
from reviewforge.renderer import render_html, write_site
from reviewforge.sources import ManualSource

OFFLINE = "http://127.0.0.1:1"
BASE = {
    "name": "Summit Ridge Roofing",
    "category": "Roofing Contractor",
    "city": "Asheville, NC",
    "phone": "(828) 555-0147",
    "website": "https://summitridgeroofing.example",
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


def test_astra_is_the_default():
    c, doc = _page()
    assert render_html(c) == render_html(c, theme="astra")
    assert 'class="container site-header__inner"' in doc
    assert 'class="wrap"' not in doc
    classic_doc = render_html(c, theme="classic")
    assert 'class="wrap"' in classic_doc
    assert "site-header__inner" not in classic_doc
    with pytest.raises(ValueError):
        render_html(c, theme="neon")


def test_key_landmarks_in_order():
    c, doc = _page()
    landmarks = [
        '<a class="skip-link" href="#main-content">',
        '<header class="site-header">',
        '<main id="main-content"',
        '<section id="home" class="hero hero--type"',
        '<section id="services"',
        '<section id="reviews"',
        '<section id="about"',
        '<section id="contact"',
        '</main>',
        '<footer class="site-footer">',
        '<div class="mobile-call-bar">',
        '</body>'
    ]
    
    positions = []
    for landmark in landmarks:
        pos = doc.find(landmark)
        assert pos != -1, f"Landmark '{landmark}' not found"
        positions.append(pos)
    
    # Check strictly increasing order
    assert positions == sorted(positions), "Landmarks are not in the correct order"
    
    assert doc.count("<h1") == 1
    assert doc.startswith("<!doctype html>")
    assert '<html lang="en">' in doc
    assert 'id="work"' not in doc


def test_testimonials_are_verbatim():
    c, doc = _page()
    for t in c.testimonials:
        quote_html = f'<blockquote class="review-card__quote"><p>{html.escape(t.text, quote=True)}</p></blockquote>'
        assert quote_html in doc
        assert "&ldquo;" not in _body(doc)
        author_html = f'<figcaption class="review-card__author">{html.escape(t.author)}'
        assert author_html in doc


def test_rating_basis_is_stated():
    # Without summary
    c, doc = _page()
    assert "4.3 out of 5" in doc
    assert "the average of the 3 reviews shown on this page" in doc
    
    # With rating_summary
    c, doc = _page(rating_summary={"average": 4.6, "count": 40, "platform": "Google"})
    assert "Rated 4.6 on Google &middot; 40 reviews" in doc
    assert "reviews shown" not in _body(doc)


def test_generated_images_flagged_disclosed_and_never_a_gallery():
    from reviewforge.generator import ImageSet, Service, SiteContent

    b = ManualSource.from_dict(BASE)
    hero = SiteImage(src="images/hero.png", origin=ORIGIN_GENERATED, role="hero",
                     width=1344, height=768)
    svc = SiteImage(src="images/service-1.png", origin=ORIGIN_GENERATED,
                    role="service", width=768, height=768)
    services = [Service("Roof Repair", "Leaks fixed.", image=svc)]
    content = SiteContent(
        business=b, hero_headline="Roofing", hero_subhead="Roofing in Asheville.",
        services=services, about="About.", cta_label="Call for a quote",
        testimonials=[], images=ImageSet(hero=hero, service_images=[svc], gallery=[SiteImage(src="gallery.png", origin=ORIGIN_GENERATED, role="gallery")]),
        provenance={},
    )
    doc = render_html(content)
    body = _body(doc)
    
    assert 'class="hero hero--photo"' in body
    assert body.count('data-illustrative="true"') == 2  # hero + service
    assert 'id="work"' not in body
    assert "illus-badge" not in body
    assert "Illustrative image" not in body
    assert ILLUSTRATIVE_DISCLOSURE in body
    assert body.index(ILLUSTRATIVE_DISCLOSURE) > body.index('<footer')
    assert 'site-footer__image-disclosure' in body


def test_business_photos_form_the_gallery_with_credits():
    from reviewforge.generator import ImageSet, SiteContent

    b = ManualSource.from_dict(BASE)
    hero = SiteImage(src="images/photo-1.jpg", origin=ORIGIN_SUPPLIED, role="hero",
                     attribution="Photo: A. Person, CC0")
    content = SiteContent(
        business=b, hero_headline="Roofing", hero_subhead="Roofing.",
        services=[], about="About.", cta_label="Call for a quote",
        testimonials=[], images=ImageSet(hero=hero, gallery=[
            SiteImage(src="gallery1.jpg", origin=ORIGIN_SUPPLIED, role="gallery", caption="Re-pipe in Boise"),
            SiteImage(src="gallery2.jpg", origin=ORIGIN_SUPPLIED, role="gallery", attribution="Photo: B. Person, CC0")
        ]), provenance={},
    )
    doc = render_html(content)
    body = _body(doc)
    
    assert 'id="work"' in body
    assert 'href="#work"' in body
    assert "Re-pipe in Boise" in body
    assert "Photo: B. Person, CC0" in body
    assert '<span class="photo-credit">Photo: A. Person, CC0</span>' in body
    assert ILLUSTRATIVE_DISCLOSURE not in body
    assert 'data-illustrative' not in body


def test_wordmark_and_logo():
    # No logo
    c, doc = _page()
    assert '<span class="brand__wordmark">Summit Ridge Roofing</span>' in doc
    
    # With logo
    from reviewforge.generator import ImageSet, SiteContent

    b = ManualSource.from_dict(BASE)
    logo = SiteImage(src="images/logo-1.png", origin=ORIGIN_SUPPLIED, role="logo", alt="Logo")
    content = SiteContent(
        business=b, hero_headline="Roofing", hero_subhead="Roofing.",
        services=[], about="About.", cta_label="Call for a quote",
        testimonials=[], images=ImageSet(logo=logo), provenance={},
    )
    doc = render_html(content)
    body = _body(doc)
    
    assert 'class="logo"' in body
    assert "brand__wordmark" not in body


def test_german_legal_links_in_footer():
    c, doc = _page(country="DE", legal={
        "impressum": "Summit GmbH\nMusterstr. 1\n10115 Berlin",
        "privacy": "https://example.com/datenschutz"
    })
    footer = doc[doc.index('<footer'):]
    
    assert '<nav class="legal-nav" aria-label="Legal information">' in footer
    assert '<a href="#legal-impressum">Impressum</a>' in footer
    assert '<a href="https://example.com/datenschutz">Datenschutz</a>' in footer
    assert 'id="legal-impressum"' in footer


def test_style_css_carries_the_trade_palette(tmp_path):
    # Plumber business
    b = ManualSource.from_dict({**BASE, "name": "Blue Line Plumbing", "category": "Plumber"})
    content = generate_site_content(b, endpoint=OFFLINE, timeout=2.0)
    write_site(content, str(tmp_path / "out"))
    
    css = (tmp_path/"out"/"style.css").read_text()
    
    # Check for the correct brand color
    assert "--brand: #175a69;" in css
    assert css.rindex("--brand: #175a69;") > css.rindex("--brand: #713b2f;")
    
    # No external assets
    assert "@import" not in css
    assert "url(" not in css
    assert "http" not in css
    
    # Check index.html for palette info
    index_html = (tmp_path/"out"/"index.html").read_text()
    assert 'palette: plumbing' in index_html
    
    # With "palette": "auto"
    b = ManualSource.from_dict({**BASE, "name": "Blue Line Plumbing", "category": "Plumber", "palette": "auto"})
    content = generate_site_content(b, endpoint=OFFLINE, timeout=2.0)
    write_site(content, str(tmp_path / "out_auto"))
    
    css = (tmp_path/"out_auto"/"style.css").read_text()
    assert "--brand: #553c4a;" in css
    
    index_html = (tmp_path/"out_auto"/"index.html").read_text()
    assert 'palette: auto' in index_html
    
    # Classic theme
    b = ManualSource.from_dict({**BASE, "name": "Blue Line Plumbing", "category": "Plumber"})
    content = generate_site_content(b, endpoint=OFFLINE, timeout=2.0)
    write_site(content, str(tmp_path / "classic"), theme="classic")
    
    css = (tmp_path/"classic"/"style.css").read_text()
    assert css == renderer.STYLE_CSS


def test_no_external_assets():
    c, doc = _page()
    assert doc.count("<link ") == 1
    assert '<link rel="stylesheet" href="style.css">' in doc
    assert "<script src" not in doc
    assert 'src="http' not in doc


def test_chat_widget_inside_the_astra_page():
    c, doc = _page(leads={"endpoint": "https://leads.example/api/lead"})
    
    assert doc.count('<script src="chat.js" defer></script>') == 1
    
    # Check placement
    footer_pos = doc.rfind("</footer>")
    body_pos = doc.rfind("</body>")
    config_pos = doc.find('<script type="application/json" id="rf-chat-config">')
    
    assert footer_pos < config_pos < body_pos
    
    # Contact section should contain lead form
    contact_pos = doc.find('id="contact"')
    lead_form_pos = doc.find('class="rf-lead-form"')
    main_pos = doc.find("</main>")
    
    assert contact_pos < lead_form_pos < main_pos
    
    # Inline CSS
    css_start = doc.find('<style id="rf-chat-css">')
    css_end = doc.find('</style>', css_start)
    inline_css = doc[css_start + 21:css_end]
    
    assert "var(--brand-ink" in inline_css
    assert "text-overflow: ellipsis" in inline_css


def test_cli_theme_flag(tmp_path):
    # Write base content to JSON file
    src = tmp_path / "biz.json"
    src.write_text(json.dumps(BASE), encoding="utf-8")
    
    from reviewforge.cli import main
    
    # Test Astra theme
    assert main(["build", "-i", str(src), "-o", str(tmp_path/"a"), "--endpoint", OFFLINE, "--images", "off"]) == 0
    index_html = (tmp_path/"a"/"index.html").read_text()
    assert "site-header__inner" in index_html
    assert 'class="wrap"' not in index_html
    
    # Test Classic theme
    assert main(["build", "-i", str(src), "-o", str(tmp_path/"c"), "--endpoint", OFFLINE, "--images", "off", "--theme", "classic"]) == 0
    index_html = (tmp_path/"c"/"index.html").read_text()
    assert 'class="wrap"' in index_html
    assert "site-header__inner" not in index_html
