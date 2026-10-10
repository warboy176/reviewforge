"""Astra renderer: SiteContent -> the default ReviewForge page design. Same honesty rules as the classic renderer: verbatim testimonials with a stated rating basis, a work gallery built only from business-owned photos, data-illustrative on every generated image plus the footer disclosure (no on-image badge), Impressum/Datenschutz links for German businesses, embedded provenance. Theming is CSS custom properties only (see reviewforge.themes)."""
from __future__ import annotations
from reviewforge.chat_render import render_chat_block, render_lead_form
from reviewforge.generator import ILLUSTRATIVE_DISCLOSURE, SiteContent, provenance_json, shown_rating_average
from reviewforge.renderer import _esc, _fmt_rating, _img_tag, _is_url, _legal_parts, _tel_href
from reviewforge.themes import palette_for

# Joined inside f-strings below: a backslash inside an f-string expression is a
# SyntaxError before Python 3.12, and the package supports 3.10+.
NL = "\n"


def astra_palette(content: SiteContent) -> str:
    return palette_for(content.business.category, content.business.palette) or palette_for(content.business.category, None)


def _stars(rating: float) -> str:
    n = max(0, min(5, int(round(rating))))
    return "★" * n + "☆" * (5 - n)


def _rating_parts(content) -> tuple[str, str] | None:
    rs = content.business.rating_summary
    if rs is not None:
        value = f"{_fmt_rating(rs.average)} out of 5"
        basis = f"Rated {_fmt_rating(rs.average)} on {_esc(rs.platform)} &middot; {rs.count} {'review' if rs.count == 1 else 'reviews'}"
    else:
        avg = shown_rating_average(content.testimonials)
        if avg is None:
            return None
        n = len(content.testimonials)
        value = f"{_fmt_rating(avg)} out of 5"
        basis = ("the rating of the 1 review shown on this page" if n == 1 else f"the average of the {n} reviews shown on this page")
    return value, basis


def render_astra_html(content: SiteContent) -> str:
    b = content.business
    iset = content.images
    tel = _tel_href(b.phone)
    phone = _esc(b.phone)
    cta = _esc(content.cta_label)
    name = _esc(b.name)
    palette = astra_palette(content)

    # Brand / wordmark. A supplied logo is used as-is; otherwise a clean
    # typographic wordmark. We never fabricate a logo mark.
    if iset.logo is not None:
        brand_inner = _img_tag(iset.logo, eager=True, extra_class="logo")
    else:
        brand_inner = f'<span class="brand__wordmark">{name}</span>'

    gallery_photos = [p for p in iset.gallery if p.is_business_own]

    rating = _rating_parts(content)

    nav_links = [
        '<a class="header-nav__link" href="#services">Services</a>',
    ]
    if gallery_photos:
        nav_links.append('<a class="header-nav__link" href="#work">Our work</a>')
    if content.testimonials:
        nav_links.append('<a class="header-nav__link" href="#reviews">Reviews</a>')
    nav_links.append('<a class="header-nav__link" href="#contact">Contact</a>')

    if b.offers_free_estimates:
        contact_lead = "Call to describe the job and ask for a free estimate, or to book a visit."
    else:
        contact_lead = "Call to describe the job, ask for a quote or book a visit."

    lead_form = render_lead_form(content)
    lead_form_html = f'          <div class="lead-form-wrap">\n{lead_form}\n          </div>\n' if lead_form else ""

    chat_block = render_chat_block(content)

    legal_links, legal_section = _legal_parts(b)

    prov = provenance_json(content).replace("</", "<\\/")

    title = f"{b.name} — {b.category} in {b.city}"
    meta_desc = _esc(content.hero_subhead[:160])

    # Hero section
    hero_class = "hero hero--photo" if iset.hero is not None else "hero hero--type"
    hero_headline = _esc(content.hero_headline)
    hero_subhead = _esc(content.hero_subhead)
    category = _esc(b.category)
    city = _esc(b.city)

    hero_content = f"""<div class="hero__content">
             <p class="eyebrow hero__eyebrow">{category} &middot; {city}</p>
             <h1 id="hero-title">{hero_headline}</h1>
             <p class="hero__subhead">{hero_subhead}</p>"""
    if rating:
        value, basis = rating
        hero_content += f"""
             <p class="rating-summary">
               <span class="rating-summary__label">Customer reviews</span>
               <span class="rating-summary__value">{value}</span>
               <span class="rating-summary__context">{basis}</span>
             </p>"""
    hero_content += f"""
             <div class="hero__actions">
               <a class="button button--accent" href="{tel}">{cta} <span aria-hidden="true">&#8599;</span></a>"""
    if content.testimonials:
        hero_content += f"""
               <a class="button button--inverse-outline" href="#reviews">Read reviews <span aria-hidden="true">&#8595;</span></a>"""
    hero_content += f"""
             </div>
             <p class="hero__phone"><span>Prefer to dial?</span> <a href="{tel}">{phone}</a></p>
           </div>"""

    hero_media = ""
    if iset.hero is not None:
        hero_media = f"""<div class="hero__media">{_img_tag(iset.hero, eager=True, extra_class="hero__image")}{f'<span class="photo-credit">{_esc(iset.hero.attribution)}</span>' if iset.hero.attribution else ''}</div>"""

    hero_section = f"""<section id="home" class="{hero_class}" aria-labelledby="hero-title">
         <div class="container hero__layout">
           {hero_content}
           {hero_media}
         </div>
       </section>"""

    # Services section
    services_heading = _esc(content.services_heading)
    services_intro = f"<p class=\"section-intro\">{_esc(content.services_intro)}</p>\n" if content.services_intro else ""
    service_cards = []
    for s in content.services:
        card_class = "service-card service-card--with-image" if s.image is not None else "service-card"
        media_html = f"<div class=\"service-card__media\">{_img_tag(s.image)}</div>\n" if s.image else ""
        desc_html = f"<p class=\"service-card__description\">{_esc(s.description)}</p>\n" if s.description else ""
        service_cards.append(f"""            <li class="{card_class}">
              {media_html}              <div class="service-card__body">
                <h3 class="service-card__title">{_esc(s.title)}</h3>
                {desc_html}              </div>
            </li>""")
    services_section = f"""<section id="services" class="section services" aria-labelledby="services-title">
         <div class="container">
           <div class="section-heading">
             <p class="eyebrow">Our services</p>
             <h2 id="services-title">{services_heading}</h2>
             {services_intro}
           </div>
           <ul class="services__grid">
             {NL.join(service_cards)}
           </ul>
           <div class="section-endnote">
             <p>Want to discuss what you need?</p>
             <a class="text-link" href="{tel}">Give us a call <span aria-hidden="true">&#8599;</span></a>
           </div>
         </div>
       </section>"""

    # Work gallery section
    work_section = ""
    if gallery_photos:
        work_items = []
        for p in gallery_photos:
            caption_html = ""
            if p.caption or p.attribution:
                inner = _esc(p.caption) if p.caption else ""
                if p.attribution:
                    inner += f'<span class="credit">{_esc(p.attribution)}</span>'
                caption_html = f"""<figcaption class="work-card__caption">{inner}</figcaption>"""
            work_items.append(f"""            <li class="work__item"><figure class="work-card"><div class="work-card__media">{_img_tag(p)}</div>{caption_html}</figure></li>""")
        work_section = f"""<section id="work" class="section work" aria-labelledby="work-title">
         <div class="container">
           <div class="section-heading">
             <p class="eyebrow">Our work</p>
             <h2 id="work-title">A closer look.</h2>
             <p class="section-intro">Photographs supplied by {name} of jobs it has completed.</p>
           </div>
           <ul class="work__grid">
             {NL.join(work_items)}
           </ul>
         </div>
       </section>"""

    # Testimonials section
    testimonials_section = ""
    if content.testimonials:
        reviews_summary = ""
        if rating:
            value, basis = rating
            reviews_summary = f"""<p class="reviews__summary"><strong>{value}</strong><span>{basis}</span></p>"""
        review_items = []
        for t in content.testimonials:
            n = max(0, min(5, int(round(t.rating))))
            stars = _stars(t.rating)
            meta_html = ""
            if t.date or (t.source_url and _is_url(t.source_url)):
                meta_html = "<span class=\"review-card__meta\">"
                if t.date:
                    meta_html += _esc(t.date)
                if t.source_url and _is_url(t.source_url):
                    meta_html += (" &middot; " if t.date else "") + f'<a href="{_esc(t.source_url)}">original review</a>'
                meta_html += "</span>"
            review_items.append(f"""            <li class="reviews__item">
               <figure class="review-card">
                 <p class="review-card__rating"><span class="review-card__stars" aria-hidden="true">{stars}</span><span class="review-card__rating-text">{n} out of 5 stars</span></p>
                 <blockquote class="review-card__quote"><p>{_esc(t.text)}</p></blockquote>
                 <figcaption class="review-card__author">{_esc(t.author)}{meta_html}</figcaption>
               </figure>
             </li>""")
        testimonials_section = f"""<section id="reviews" class="section reviews" aria-labelledby="reviews-title">
         <div class="container">
           <div class="section-heading section-heading--split">
             <div>
               <p class="eyebrow">Customer reviews</p>
               <h2 id="reviews-title">In their own words.</h2>
               <p class="section-intro">Customer reviews supplied by {name}, reproduced word for word.</p>
             </div>
             {reviews_summary}
           </div>
           <ul class="reviews__grid">
             {NL.join(review_items)}
           </ul>
         </div>
       </section>"""

    # About section
    about_section = f"""<section id="about" class="section about" aria-labelledby="about-title">
         <div class="container about__layout">
           <div class="section-heading">
             <p class="eyebrow">About us</p>
             <h2 id="about-title">{name}</h2>
           </div>
           <div class="about__content">
             <p class="about__text">{_esc(content.about)}</p>
             <div class="about__service-area">
               <h3>Where we work</h3>
               <p>{city}</p>
             </div>
           </div>
         </div>
       </section>"""

    # Contact section
    contact_lead = _esc(contact_lead)
    website = _esc(b.website) if b.website else ""
    hours = _esc(b.hours) if b.hours else ""
    contact_section = f"""<section id="contact" class="section contact" aria-labelledby="contact-title">
         <div class="container contact__layout">
           <div class="contact__intro">
             <p class="eyebrow">Get in touch</p>
             <h2 id="contact-title">Tell us what you need.</h2>
             <p class="contact__lead">{contact_lead}</p>
             <a class="button button--accent" href="{tel}">{cta} <span aria-hidden="true">&#8599;</span></a>
{lead_form_html}        </div>
           <div class="contact__details">
             <h3>Contact details</h3>
             <dl class="contact-list">
               <div class="contact-list__row"><dt>Phone</dt><dd><a href="{tel}">{phone}</a></dd></div>
               {f'<div class="contact-list__row"><dt>Website</dt><dd><a href="{website}">{website}</a></dd></div>' if b.website else ''}
               <div class="contact-list__row"><dt>Service area</dt><dd>{city}</dd></div>
               {f'<div class="contact-list__row"><dt>Hours</dt><dd>{hours}</dd></div>' if b.hours else ''}
             </dl>
           </div>
         </div>
       </section>"""

    # Footer
    legal_links_html = " ".join(legal_links) if legal_links else ""
    website_link = f'<p class="site-footer__website"><a href="{website}">{website}</a></p>\n' if b.website else ""
    disclosure_html = f'<p class="site-footer__disclosure site-footer__image-disclosure">{_esc(ILLUSTRATIVE_DISCLOSURE)}</p>\n' if iset.uses_illustrative else ""
    testimonials_disclosure = f'<p class="site-footer__disclosure">Testimonials are reproduced verbatim from reviews supplied by {name}.</p>\n' if content.testimonials else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{_esc(title)}</title>
  <meta name="description" content="{meta_desc}">
  <meta name="generator" content="ReviewForge (theme: astra, palette: {palette})">
  <link rel="stylesheet" href="style.css">
  <!-- Built by ReviewForge. Testimonials are verbatim excerpts of reviews
       supplied by the business. Every image's origin is listed in the
       provenance block below; images the business did not supply carry a
       data-illustrative attribute and are disclosed in the footer. -->
  <script type="application/json" id="reviewforge-provenance">
{prov}
  </script>
</head>
<body>
  <a class="skip-link" href="#main-content">Skip to main content</a>
  <header class="site-header">
    <div class="container site-header__inner">
      <a class="brand" href="#home" aria-label="{name}: home">{brand_inner}</a>
      <nav class="header-nav" aria-label="Primary navigation">
        {NL.join(nav_links)}
        <a class="button button--brand header-call" href="{tel}"><span class="header-call__label">Call us</span><span class="header-call__number">{phone}</span></a>
      </nav>
    </div>
  </header>

  <main id="main-content" tabindex="-1">
{hero_section}
{services_section}
{work_section}
{testimonials_section}
{about_section}
{contact_section}
  </main>

  <footer class="site-footer">
    <div class="container">
      <div class="site-footer__top">
        <p class="site-footer__business">{name}</p>
        {f'<nav class="legal-nav" aria-label="Legal information">{legal_links_html}</nav>' if legal_links else ''}
      </div>
      {website_link}
      {testimonials_disclosure}
      {disclosure_html}
{legal_section}      <div class="site-footer__bottom">
        <p>&copy; {name} &middot; {city}</p>
        <p class="site-footer__credit">Site built with ReviewForge.</p>
      </div>
    </div>
  </footer>
  <div class="mobile-call-bar">
    <a class="button button--brand mobile-call-bar__button" href="{tel}"><span>{cta}</span><span class="mobile-call-bar__number">{phone}</span></a>
  </div>
{chat_block}</body>
</html>"""
