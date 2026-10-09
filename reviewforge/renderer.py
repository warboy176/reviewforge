"""Renderer: SiteContent -> a clean, dependency-light static site.

Output is semantic HTML5 + one hand-written CSS file. No frameworks, no
JavaScript (except the optional, self-hosted lead widget), no trackers, no
analytics, no external fonts or CDNs. Mobile-first,
accessible (landmarks, good contrast, alt text, focus styles, tel: links).

Imagery rules enforced here, not just documented:
  * the work gallery renders **only** images the business actually owns;
  * every illustrative image is emitted with ``data-illustrative="true"``;
  * when any illustrative image appears, the footer carries a plain-English
    disclosure;
  * no logo is ever synthesised -- with no supplied logo we render a
    typographic wordmark;
  * images carry ``width``/``height`` (no layout shift) and ``loading="lazy"``
    everywhere except the above-the-fold hero.
"""
from __future__ import annotations

import html
import os
import re

from reviewforge.generator import (
    ILLUSTRATIVE_DISCLOSURE,
    SiteContent,
    provenance_json,
    shown_rating_average,
)
from reviewforge.models import SiteImage
from reviewforge.chat_render import render_chat_block, render_lead_form, write_chat_assets

STYLE_CSS = """\
/* ReviewForge - clean, dependency-light, accessible. No external assets. */
:root {
  --bg: #ffffff;
  --surface: #f5f7fa;
  --ink: #1a2230;
  --muted: #55617a;
  --brand: #12507b;
  --brand-dark: #0d3a59;
  --accent: #e8a13a;
  --star: #e0a526;
  --border: #d7dee8;
  --radius: 12px;
  --maxw: 960px;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: var(--ink);
  background: var(--bg);
  line-height: 1.6;
  font-size: 18px;
}
a { color: var(--brand); }
h1, h2, h3 { line-height: 1.2; color: var(--ink); }
img { max-width: 100%; height: auto; display: block; }

.wrap { max-width: var(--maxw); margin: 0 auto; padding: 0 20px; }

a.skip-link {
  position: absolute; left: -999px; top: 0;
  background: var(--brand); color: #fff; padding: 10px 16px; z-index: 100;
}
a.skip-link:focus { left: 8px; top: 8px; }

/* Header / nav */
.site-header {
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0; background: var(--bg); z-index: 20;
}
.site-header .wrap {
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; padding-top: 14px; padding-bottom: 14px;
}
.brand { min-width: 0; }
.brand { font-weight: 700; font-size: 1.15rem; color: var(--brand-dark); }
.brand small { display: block; font-weight: 400; color: var(--muted); font-size: 0.8rem; }
/* Typographic wordmark -- used when the business supplies no logo. We never
   synthesise a logo mark. */
.wordmark { display: flex; align-items: center; gap: 12px; }
.wordmark .mono {
  flex: 0 0 auto;
  width: 40px; height: 40px; border-radius: 10px;
  background: var(--brand-dark); color: #fff;
  display: grid; place-items: center;
  font-weight: 800; letter-spacing: 0.5px; font-size: 0.95rem;
}
.wordmark img.logo { width: auto; height: 42px; }
.header-cta {
  background: var(--brand); color: #fff; text-decoration: none;
  padding: 10px 18px; border-radius: 999px; font-weight: 600; white-space: nowrap;
}
.header-cta:hover, .header-cta:focus { background: var(--brand-dark); }

/* Hero */
.hero {
  background: linear-gradient(160deg, var(--brand-dark), var(--brand));
  color: #fff; padding: 64px 0;
}
.hero h1 { color: #fff; font-size: clamp(1.9rem, 5vw, 3rem); margin: 0 0 14px; }
.hero p { font-size: clamp(1.05rem, 2.5vw, 1.3rem); color: #eaf2f8; margin: 0 0 28px; max-width: 42ch; }
.hero .rating-line { font-weight: 600; margin-bottom: 20px; color: #fff; max-width: none; }
.hero .stars { color: #ffd87a; letter-spacing: 2px; }

/* Hero with a photograph: real <img> (so alt text, width/height and
   fetchpriority all work) under a gradient scrim that keeps text contrast
   well above WCAG AA regardless of the picture underneath. */
.hero.has-image { position: relative; padding: 0; overflow: hidden; background: var(--brand-dark); }
.hero.has-image .hero-media { position: absolute; inset: 0; }
.hero.has-image .hero-media img {
  width: 100%; height: 100%; object-fit: cover; display: block;
}
.hero.has-image .scrim {
  position: absolute; inset: 0;
  background:
    linear-gradient(90deg, rgba(8,24,38,0.90) 0%, rgba(8,24,38,0.72) 46%, rgba(8,24,38,0.30) 100%),
    linear-gradient(0deg, rgba(8,24,38,0.58) 0%, rgba(8,24,38,0.10) 62%);
}
.hero.has-image .hero-body { position: relative; padding: 84px 0 84px; }
.hero.has-image p { color: #f1f6fa; text-shadow: 0 1px 2px rgba(0,0,0,0.35); }
.hero.has-image h1 { text-shadow: 0 2px 6px rgba(0,0,0,0.45); }

.btn {
  display: inline-block; background: var(--accent); color: #2a1c00;
  text-decoration: none; padding: 14px 26px; border-radius: 999px;
  font-weight: 700; font-size: 1.05rem;
}
.btn:hover, .btn:focus { background: #f0b24e; }
.btn.secondary { background: transparent; color: #fff; border: 2px solid #fff; margin-left: 10px; }
.btn.secondary:hover, .btn.secondary:focus { background: rgba(255,255,255,0.12); }
.hero .btn-row { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
.hero .btn.secondary { margin-left: 0; }

section { padding: 56px 0; }
section h2 { font-size: clamp(1.5rem, 4vw, 2rem); margin: 0 0 8px; }
.section-intro { color: var(--muted); margin: 0 0 32px; }
section h2 + .service-grid { margin-top: 24px; }

/* Photo credit for openly licensed images, shown on the picture. */
.media { position: relative; }
.photo-credit {
  position: absolute; z-index: 2;
  font-size: 0.75rem; line-height: 1.2; font-weight: 600; letter-spacing: 0.2px;
  color: #fff; background: rgba(8,20,32,0.82);
  padding: 4px 9px; border-radius: 6px; pointer-events: none;
}
.hero .photo-credit { left: auto; right: 14px; bottom: 14px; }
.photo-credit { font-weight: 400; max-width: 60%; }

/* Services */
.services { background: var(--surface); }
.service-grid {
  display: grid; gap: 20px;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}
@media (min-width: 900px) {
  .service-grid.n4 { grid-template-columns: repeat(4, 1fr); }
  .service-grid.n4 .service-card .card-body { padding: 18px 18px 20px; }
}
@media (min-width: 560px) and (max-width: 899px) {
  .service-grid.n4 { grid-template-columns: repeat(2, 1fr); }
}
.service-card {
  background: var(--bg); border: 1px solid var(--border);
  border-radius: var(--radius); overflow: hidden;
  display: flex; flex-direction: column;
}
.service-card .card-media { background: var(--surface); }
.service-card .card-media img {
  width: 100%; aspect-ratio: 4 / 3; object-fit: cover;
}
/* A card with no picture, in a row of cards that have one: a quiet brand
   panel of the same height keeps the row even. Deliberately not a picture. */
.service-card .card-media.blank {
  aspect-ratio: 4 / 3; display: grid; place-items: center;
  background: linear-gradient(150deg, var(--brand-dark), var(--brand));
}
.service-card .card-media.blank span {
  color: rgba(255,255,255,0.9); font-size: 2.6rem; font-weight: 800;
}
.service-card .card-body { padding: 22px 24px 24px; }
.service-card h3 { margin: 0 0 8px; font-size: 1.15rem; color: var(--brand-dark); overflow-wrap: anywhere; }
.service-card p { margin: 0; color: var(--muted); }

/* Honest little note wherever illustrative imagery is shown. */
.imagery-note {
  margin: 24px 0 0; color: var(--muted); font-size: 0.85rem;
  border-left: 3px solid var(--border); padding-left: 12px; max-width: 62ch;
}

/* Work gallery -- business-owned photos ONLY. */
.gallery-grid {
  display: grid; gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}
.gallery-grid figure {
  margin: 0; border: 1px solid var(--border); border-radius: var(--radius);
  overflow: hidden; background: var(--bg);
  display: flex; flex-direction: column;
}
.gallery-grid img { width: 100%; aspect-ratio: 3 / 2; object-fit: cover; }
.gallery-grid figcaption {
  padding: 12px 16px; color: var(--ink); font-size: 0.95rem;
}
.gallery-grid figcaption .credit {
  display: block; margin-top: 4px; color: var(--muted); font-size: 0.8rem;
}

/* Testimonials */
.testimonial-grid {
  display: grid; gap: 20px;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
}
.testimonial {
  margin: 0; border: 1px solid var(--border); border-radius: var(--radius);
  padding: 24px; background: var(--bg);
  display: flex; flex-direction: column;
}
.testimonial .stars { color: var(--star); letter-spacing: 2px; font-size: 1.05rem; }
.testimonial blockquote { margin: 12px 0 16px; font-size: 1.02rem; flex: 1 1 auto; }
.testimonial figcaption { color: var(--muted); font-size: 0.95rem; }
.testimonial figcaption .name { color: var(--ink); font-weight: 600; }

/* About + contact */
.about p { max-width: 65ch; }
.contact { background: var(--surface); }
.contact-grid { display: grid; gap: 24px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
.contact dl { margin: 0; }
.contact dt { font-weight: 700; color: var(--brand-dark); margin-top: 14px; }
.contact dd { margin: 0; }
.contact a.phone { font-size: 1.4rem; font-weight: 700; color: var(--brand-dark); text-decoration: none; }

/* Footer */
.site-footer {
  border-top: 1px solid var(--border); padding: 28px 0;
  color: var(--muted); font-size: 0.9rem;
}
.site-footer p { margin: 4px 0; }
.site-footer .disclosure { max-width: 70ch; }
.site-footer nav a { margin-right: 4px; }
.legal-text { margin-top: 18px; max-width: 70ch; }
.legal-text h2 { font-size: 1rem; margin: 14px 0 4px; color: var(--ink); }
.legal-text p { white-space: pre-line; }

:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
}

@media (max-width: 640px) {
  body { font-size: 17px; }
  .hero { padding: 48px 0 56px; }
  .hero.has-image .hero-body { padding: 56px 0 64px; }
  .site-header { position: static; }
  .site-header .wrap { padding-top: 10px; padding-bottom: 10px; gap: 10px; }
  .brand { font-size: 1rem; }
  .wordmark .mono { width: 36px; height: 36px; }
  .wordmark img.logo { height: 36px; }
  .header-cta { padding: 8px 16px; font-size: 0.95rem; }
  .header-cta .num { display: none; }
  section { padding: 44px 0; }
  .hero.has-image .scrim {
    background: linear-gradient(0deg, rgba(8,24,38,0.93) 10%, rgba(8,24,38,0.72) 100%);
  }
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #11161f; --surface: #1a212d; --ink: #e8edf4; --muted: #a2afc4;
    --brand: #4aa3d6; --brand-dark: #2e7fb0; --border: #2a3444;
  }
}
"""


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _tel_href(phone: str) -> str:
    digits = re.sub(r"[^0-9+]", "", phone)
    return f"tel:{digits}" if digits else "#contact"


def _initials(name: str) -> str:
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", name or "") if p]
    if not parts:
        return "·"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _img_tag(
    image: SiteImage,
    *,
    eager: bool = False,
    extra_class: str = "",
) -> str:
    """Render one <img>, carrying its provenance in the markup.

    ``data-illustrative`` is emitted for anything the business did not supply,
    so the honesty flag survives into the shipped HTML and is inspectable by
    anyone reading the page source -- not only by whoever reads
    provenance.json.
    """
    attrs = [f'src="{_esc(image.src)}"', f'alt="{_esc(image.alt)}"']
    if extra_class:
        attrs.append(f'class="{_esc(extra_class)}"')
    if image.width:
        attrs.append(f'width="{int(image.width)}"')
    if image.height:
        attrs.append(f'height="{int(image.height)}"')
    if eager:
        attrs.append('loading="eager"')
        attrs.append('fetchpriority="high"')
    else:
        attrs.append('loading="lazy"')
    attrs.append('decoding="async"')
    attrs.append(f'data-image-origin="{_esc(image.origin)}"')
    if image.illustrative:
        attrs.append('data-illustrative="true"')
    return "<img " + " ".join(attrs) + ">"


def _stars(avg: float) -> str:
    n = max(0, min(5, int(round(avg))))
    return "★" * n + "☆" * (5 - n)


def _fmt_rating(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".") if x != int(x) else f"{int(x)}"


def _rating_html(content: SiteContent) -> str:
    """The hero rating line.

    With a supplied ``rating_summary`` it states the platform figure
    ("4.6 on Google · 40 reviews"). Without one it states only the average of
    the reviews actually shown, worded so a hand-picked subset cannot read as
    the business's overall rating.
    """
    rs = content.business.rating_summary
    if rs is not None:
        text = (
            f"{_fmt_rating(rs.average)} on {_esc(rs.platform)} &middot; "
            f"{rs.count} {'review' if rs.count == 1 else 'reviews'}"
        )
        stars = _stars(rs.average)
    else:
        avg = shown_rating_average(content.testimonials)
        if avg is None:
            return ""
        n = len(content.testimonials)
        text = (
            f"{_fmt_rating(avg)} out of 5 &middot; average of the "
            f"{'review' if n == 1 else f'{n} reviews'} shown"
        )
        stars = _stars(avg)
    return (
        f'<p class="rating-line"><span class="stars" aria-hidden="true">{stars}</span> '
        f"{text}</p>"
    )


def _is_url(value: str) -> bool:
    return bool(re.match(r"^https?://", value or "", re.IGNORECASE))


def _legal_parts(b) -> tuple[list[str], str]:
    """Footer links and (optional) inline legal text section."""
    german = b.country == "DE"
    labels = {
        "impressum": "Impressum" if german else "Legal notice",
        "privacy": "Datenschutz" if german else "Privacy",
    }
    links: list[str] = []
    blocks = ""
    for key in ("impressum", "privacy"):
        value = getattr(b.legal, key)
        if not value:
            continue
        if _is_url(value):
            links.append(f'<a href="{_esc(value)}">{labels[key]}</a>')
        else:
            links.append(f'<a href="#legal-{key}">{labels[key]}</a>')
            blocks += (
                f'        <h2 id="legal-{key}">{labels[key]}</h2>\n'
                f"        <p>{_esc(value)}</p>\n"
            )
    section = ""
    if blocks:
        section = f'      <div class="legal-text">\n{blocks}      </div>\n'
    return links, section


def render_css() -> str:
    return STYLE_CSS


def render_html(content: SiteContent) -> str:
    b = content.business
    tel = _tel_href(b.phone)
    iset = content.images

    # Brand / wordmark. A supplied logo is used as-is; otherwise a clean
    # typographic wordmark. We never fabricate a logo mark.
    if iset.logo is not None:
        brand_mark = _img_tag(iset.logo, eager=True, extra_class="logo")
    else:
        brand_mark = f'<span class="mono" aria-hidden="true">{_esc(_initials(b.name))}</span>'
    brand_html = f"""<div class="brand wordmark">
        {brand_mark}
        <span>{_esc(b.name)}<small>{_esc(b.category)} &middot; {_esc(b.city)}</small></span>
      </div>"""

    rating_html = _rating_html(content)

    reviews_btn = (
        '\n          <a class="btn secondary" href="#reviews">Read reviews</a>'
        if content.testimonials else ""
    )
    hero_inner = f"""<h1 id="hero-h">{_esc(content.hero_headline)}</h1>
        <p>{_esc(content.hero_subhead)}</p>
        {rating_html}
        <div class="btn-row">
          <a class="btn" href="{tel}">{_esc(content.cta_label)}</a>{reviews_btn}
        </div>"""

    if iset.hero is not None:
        hero_label = ""
        if iset.hero.attribution:
            hero_label = f'<span class="photo-credit">{_esc(iset.hero.attribution)}</span>'
        hero_section = f"""    <section class="hero has-image" aria-labelledby="hero-h">
      <div class="hero-media">{_img_tag(iset.hero, eager=True)}</div>
      <div class="scrim" aria-hidden="true"></div>
      <div class="hero-body">
        <div class="wrap">
        {hero_inner}
        </div>
      </div>
      {hero_label}
    </section>"""
    else:
        hero_section = f"""    <section class="hero" aria-labelledby="hero-h">
      <div class="wrap">
        {hero_inner}
      </div>
    </section>"""

    # Services, with optional card imagery. If some cards have a picture and
    # some do not, the bare ones get a plain brand panel so the row stays even.
    any_media = any(s.image is not None for s in content.services)
    service_cards = ""
    for s in content.services:
        media = ""
        if s.image is not None:
            media = (
                f'          <div class="card-media media">{_img_tag(s.image)}'
                f"</div>\n"
            )
        elif any_media:
            initial = _esc((s.title.strip() or "·")[0].upper())
            media = (
                f'          <div class="card-media blank" aria-hidden="true">'
                f"<span>{initial}</span></div>\n"
            )
        desc = f"<p>{_esc(s.description)}</p>" if s.description else ""
        service_cards += f"""        <article class="service-card">
{media}          <div class="card-body">
            <h3>{_esc(s.title)}</h3>
            {desc}
          </div>
        </article>
"""
    grid_class = "service-grid n4" if len(content.services) == 4 else "service-grid"
    services_intro = (
        f'        <p class="section-intro">{_esc(content.services_intro)}</p>\n'
        if content.services_intro else ""
    )

    # Work gallery. HARD RULE: business-owned photos only. Anything
    # illustrative is filtered out here as well as in the generator, so a
    # future change in one place cannot quietly turn generated imagery into a
    # portfolio.
    gallery_photos = [p for p in iset.gallery if p.is_business_own]
    gallery_section = ""
    if gallery_photos:
        figures = ""
        for p in gallery_photos:
            cap = ""
            if p.caption or p.attribution:
                inner = _esc(p.caption) if p.caption else ""
                if p.attribution:
                    inner += f'<span class="credit">{_esc(p.attribution)}</span>'
                cap = f"            <figcaption>{inner}</figcaption>\n"
            figures += f"""          <figure>
            {_img_tag(p)}
{cap}          </figure>
"""
        gallery_section = f"""    <section class="gallery" id="work" aria-labelledby="work-h">
      <div class="wrap">
        <h2 id="work-h">Our work</h2>
        <p class="section-intro">Photographs supplied by {_esc(b.name)} of jobs it has completed.</p>
        <div class="gallery-grid">
{figures}        </div>
      </div>
    </section>

"""

    # Testimonials (verbatim, attributed as supplied)
    testimonial_cards = ""
    for t in content.testimonials:
        n = max(0, min(5, int(round(t.rating))))
        stars = "★" * n + "☆" * (5 - n)
        meta = f'<span class="name">{_esc(t.author)}</span>'
        if t.date:
            meta += f" &middot; {_esc(t.date)}"
        if t.source_url and _is_url(t.source_url):
            meta += f' &middot; <a href="{_esc(t.source_url)}">original review</a>'
        testimonial_cards += f"""        <figure class="testimonial">
          <div class="stars" aria-hidden="true">{stars}</div>
          <span class="visually-hidden-label">Rated {n:g} out of 5.</span>
          <blockquote>&ldquo;{_esc(t.text)}&rdquo;</blockquote>
          <figcaption>{meta}</figcaption>
        </figure>
"""

    testimonials_section = ""
    if content.testimonials:
        testimonials_section = f"""    <section id="reviews" aria-labelledby="reviews-h">
      <div class="wrap">
        <h2 id="reviews-h">What customers say</h2>
        <p class="section-intro">Customer reviews supplied by {_esc(b.name)}, reproduced word for word.</p>
        <div class="testimonial-grid">
{testimonial_cards}        </div>
      </div>
    </section>"""

    # Contact rows (omit missing fields -- never fabricate)
    contact_rows = f"""          <dt>Phone</dt>
          <dd><a class="phone" href="{tel}">{_esc(b.phone)}</a></dd>
          <dt>Service area</dt>
          <dd>{_esc(b.city)}</dd>"""
    if b.hours:
        contact_rows += f"""
          <dt>Hours</dt>
          <dd>{_esc(b.hours)}</dd>"""
    if b.website:
        contact_rows += f"""
          <dt>Website</dt>
          <dd><a href="{_esc(b.website)}">{_esc(b.website)}</a></dd>"""

    if b.offers_free_estimates:
        contact_lead = (
            "Call to describe the job and ask for a free estimate, or to book "
            "a visit."
        )
    else:
        contact_lead = "Call to describe the job, ask for a quote or book a visit."

    website_link = ""
    if b.website:
        website_link = f' &middot; <a href="{_esc(b.website)}">{_esc(b.website)}</a>'

    # Footer disclosure -- mandatory whenever any illustrative image is shown.
    disclosure_html = ""
    if iset.uses_illustrative:
        disclosure_html = (
            f'      <p class="disclosure">{_esc(ILLUSTRATIVE_DISCLOSURE)}</p>\n'
        )

    nav = ['<a href="#services">Services</a>']
    if gallery_photos:
        nav.append('<a href="#work">Our work</a>')
    if content.testimonials:
        nav.append('<a href="#reviews">Reviews</a>')
    nav.append('<a href="#contact">Contact</a>')
    legal_links, legal_section = _legal_parts(b)
    nav += legal_links
    nav_links = " &middot; ".join(nav)

    # Machine-readable provenance, embedded for auditability.
    prov = provenance_json(content).replace("</", "<\\/")

    # Optional lead-capture widget: ONE self-contained block before </body>,
    # plus a no-JS form in the contact section. Both are empty strings unless
    # business.json has a "leads" block.
    chat_block = render_chat_block(content)
    lead_form = render_lead_form(content)
    lead_form_html = (
        f'        <div class="lead-form-wrap">\n{lead_form}        </div>\n'
        if lead_form else ""
    )

    title = f"{b.name} — {b.category} in {b.city}"
    meta_desc = _esc(content.hero_subhead[:160])

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <meta name="description" content="{meta_desc}">
  <link rel="stylesheet" href="style.css">
  <style>.visually-hidden-label{{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}}</style>
  <!-- Built by ReviewForge. Testimonials are verbatim excerpts of reviews
       supplied by the business. Every image's origin is listed in the
       provenance block below; images the business did not supply carry a
       data-illustrative attribute and are disclosed in the footer. -->
  <script type="application/json" id="reviewforge-provenance">
{prov}
  </script>
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  <header class="site-header">
    <div class="wrap">
      {brand_html}
      <a class="header-cta" href="{tel}">Call<span class="num"> {_esc(b.phone)}</span></a>
    </div>
  </header>

  <main id="main">
{hero_section}

    <section class="services" id="services" aria-labelledby="services-h">
      <div class="wrap">
        <h2 id="services-h">{_esc(content.services_heading)}</h2>
{services_intro}        <div class="{grid_class}">
{service_cards}        </div>
      </div>
    </section>

{gallery_section}{testimonials_section}

    <section class="about" id="about" aria-labelledby="about-h">
      <div class="wrap">
        <h2 id="about-h">About {_esc(b.name)}</h2>
        <p>{_esc(content.about)}</p>
      </div>
    </section>

    <section class="contact" id="contact" aria-labelledby="contact-h">
      <div class="wrap">
        <h2 id="contact-h">Get in touch</h2>
        <div class="contact-grid">
          <div>
            <p>{contact_lead}</p>
            <p><a class="btn" href="{tel}">{_esc(content.cta_label)}</a></p>
          </div>
          <dl>
{contact_rows}
          </dl>
        </div>
{lead_form_html}      </div>
    </section>
  </main>

  <footer class="site-footer">
    <div class="wrap">
      <p>&copy; {_esc(b.name)} &middot; {_esc(b.city)}{website_link}</p>
      <nav aria-label="Footer"><p>{nav_links}</p></nav>
      <p>Site built with ReviewForge. Testimonials are reproduced verbatim from reviews supplied by {_esc(b.name)}.</p>
{disclosure_html}{legal_section}    </div>
  </footer>
{chat_block}</body>
</html>
"""


def write_site(content: SiteContent, out_dir: str) -> dict:
    """Write index.html, style.css and provenance.json to out_dir.

    Image assets are written during content generation (they have to exist
    before the markup can state their pixel dimensions), so this only emits
    the text files.

    chat.js is written only when the business configured leads.
    """
    os.makedirs(out_dir, exist_ok=True)
    index_path = os.path.join(out_dir, "index.html")
    css_path = os.path.join(out_dir, "style.css")
    prov_path = os.path.join(out_dir, "provenance.json")

    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(render_html(content))
    with open(css_path, "w", encoding="utf-8") as fh:
        fh.write(render_css())
    with open(prov_path, "w", encoding="utf-8") as fh:
        fh.write(provenance_json(content))

    extra = write_chat_assets(content, out_dir)
    return {"index": index_path, "css": css_path, "provenance": prov_path, **extra}
