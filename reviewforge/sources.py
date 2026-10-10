"""ReviewSource abstraction.

A ReviewSource loads a Business (profile + reviews + photos) from somewhere.

  * ManualSource -- reads a local JSON file. The business supplies its own
                    reviews *and its own photos*. Zero external calls, fully
                    auditable.

There is deliberately no source that pulls reviews or photos from Google or any
other platform. A static site is an indefinite copy of whatever it shows, and
platform terms (Google's Places terms among them) forbid caching their content
like that. Reviews must be ones the business has the right to republish -- for
example reviews customers sent it directly, or a platform export whose terms
allow republication. Showing live Google reviews needs a client-side widget
that fetches them at view time, which is out of scope for a static generator.
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any, Optional

from reviewforge.models import (
    ORIGIN_SUPPLIED,
    Business,
    LegalInfo,
    RatingSummary,
    Review,
    SiteImage,
)
from reviewforge.leads import parse_booking, parse_leads
from reviewforge.themes import normalize_palette

_COUNTRY_ALIASES = {
    "GERMANY": "DE", "DEUTSCHLAND": "DE", "USA": "US",
    "UNITED STATES": "US", "UK": "GB", "UNITED KINGDOM": "GB",
    "AUSTRIA": "AT", "OESTERREICH": "AT", "ÖSTERREICH": "AT",
}


def _country(raw: Any) -> Optional[str]:
    if raw in (None, ""):
        return None
    code = str(raw).strip().upper()
    code = _COUNTRY_ALIASES.get(code, code)
    if len(code) != 2 or not code.isalpha():
        raise ValueError(
            f"country {raw!r} is not an ISO 3166-1 alpha-2 code (e.g. \"US\", \"DE\")"
        )
    return code


def _rating_summary(raw: Any) -> Optional[RatingSummary]:
    if raw in (None, "", {}):
        return None
    if not isinstance(raw, dict):
        raise ValueError("'rating_summary' must be an object {average, count, platform}")
    missing = [k for k in ("average", "count", "platform") if raw.get(k) in (None, "")]
    if missing:
        raise ValueError(
            f"rating_summary is missing: {', '.join(missing)}. ReviewForge will "
            "not fill in a rating it was not given."
        )
    try:
        average = float(raw["average"])
        count = int(raw["count"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"rating_summary has a non-numeric average/count: {raw!r}") from exc
    if not 0 <= average <= 5:
        raise ValueError(f"rating_summary.average {average} is outside 0-5")
    if count < 1:
        raise ValueError("rating_summary.count must be at least 1")
    return RatingSummary(average=average, count=count, platform=str(raw["platform"]).strip())


def _legal(raw: Any) -> LegalInfo:
    if raw in (None, "", {}):
        return LegalInfo()
    if not isinstance(raw, dict):
        raise ValueError("'legal' must be an object {impressum?, privacy?}")
    unknown = set(raw) - {"impressum", "privacy"}
    if unknown:
        raise ValueError(f"'legal' has unknown key(s): {', '.join(sorted(unknown))}")

    def clean(v: Any) -> Optional[str]:
        return str(v).strip() if v not in (None, "") and str(v).strip() else None

    return LegalInfo(impressum=clean(raw.get("impressum")), privacy=clean(raw.get("privacy")))


class ReviewSource(ABC):
    """Loads a Business and its real reviews from a backing source."""

    @abstractmethod
    def load(self) -> Business:  # pragma: no cover - interface
        raise NotImplementedError


def _review_from_dict(raw: dict[str, Any], index: int) -> Review:
    """Build a Review from a raw dict, omitting missing optional fields.

    Honesty guard: we never invent an author, rating or text. A review missing
    any of those required fields is rejected loudly rather than filled in.
    """
    missing = [k for k in ("author", "rating", "text") if raw.get(k) in (None, "")]
    if missing:
        raise ValueError(
            f"review #{index} is missing required field(s): {', '.join(missing)}. "
            "ReviewForge will not fabricate review data."
        )
    try:
        rating = float(raw["rating"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"review #{index} has a non-numeric rating: {raw['rating']!r}") from exc
    if not 0 <= rating <= 5:
        raise ValueError(f"review #{index} rating {rating} is outside 0-5")

    return Review(
        author=str(raw["author"]).strip(),
        rating=rating,
        text=str(raw["text"]).strip(),
        date=(str(raw["date"]).strip() if raw.get("date") else None),
        source_index=index,
        source_url=(str(raw["source_url"]).strip() if raw.get("source_url") else None),
    )


def _photo_from_dict(raw: Any, index: int, *, role: str = "gallery") -> SiteImage:
    """Build a business-supplied SiteImage from a raw dict (or bare path).

    These are the business's **own** photos, so ``origin`` is ``supplied`` and
    ``is_business_own`` comes out True -- captions like "our new roof on a
    Craftsman in West Asheville" are legitimate here and are kept verbatim.
    """
    if isinstance(raw, str):
        raw = {"src": raw}
    if not isinstance(raw, dict):
        raise ValueError(f"photo #{index} must be an object or a path string")
    src = str(raw.get("src") or "").strip()
    if not src:
        raise ValueError(
            f"photo #{index} is missing 'src'. ReviewForge will not substitute a "
            "generated image for a missing real photo."
        )
    width = raw.get("width")
    height = raw.get("height")
    return SiteImage(
        src=src,
        alt=str(raw.get("alt") or "").strip(),
        caption=(str(raw["caption"]).strip() if raw.get("caption") else None),
        origin=ORIGIN_SUPPLIED,
        role=str(raw.get("role") or role).strip() or role,
        width=int(width) if width else None,
        height=int(height) if height else None,
        attribution=(str(raw["attribution"]).strip() if raw.get("attribution") else None),
    )


def _business_from_dict(data: dict[str, Any]) -> Business:
    required = ["name", "category", "city", "phone"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise ValueError(f"business is missing required field(s): {', '.join(missing)}")

    raw_reviews = data.get("reviews") or []
    if not isinstance(raw_reviews, list):
        raise ValueError("'reviews' must be a list")
    reviews = [_review_from_dict(r, i) for i, r in enumerate(raw_reviews)]

    raw_photos = data.get("photos") or []
    if not isinstance(raw_photos, list):
        raise ValueError("'photos' must be a list of {src, alt?, caption?} objects")
    photos = [_photo_from_dict(p, i) for i, p in enumerate(raw_photos)]

    logo: Optional[SiteImage] = None
    if data.get("logo"):
        # Only ever a logo the business actually has. ReviewForge does not
        # generate logos -- the renderer falls back to a typographic wordmark.
        logo = _photo_from_dict(data["logo"], 0, role="logo")

    free = data.get("offers_free_estimates", False)
    if not isinstance(free, bool):
        raise ValueError("'offers_free_estimates' must be true or false")

    # Optional fields are omitted (left as None) when absent -- never fabricated.
    business = Business(
        name=str(data["name"]).strip(),
        category=str(data["category"]).strip(),
        city=str(data["city"]).strip(),
        phone=str(data["phone"]).strip(),
        website=(str(data["website"]).strip() if data.get("website") else None),
        hours=(str(data["hours"]).strip() if data.get("hours") else None),
        reviews=reviews,
        photos=photos,
        logo=logo,
        offers_free_estimates=free,
        rating_summary=_rating_summary(data.get("rating_summary")),
        country=_country(data.get("country")),
        legal=_legal(data.get("legal")),
        leads=parse_leads(data.get("leads")),
        booking=parse_booking(data.get("booking")),
        palette=normalize_palette(data.get("palette")),
    )
    if business.booking is not None and business.leads is None:
        raise ValueError(
            "'booking' needs a 'leads' block too: a booking request is also sent "
            "to the business as a lead, so it must have somewhere to go."
        )
    # Fails the load (and therefore the build) for DE without legal pages.
    business.legal_warnings()
    return business


class ManualSource(ReviewSource):
    """Reads a Business from a local JSON file.

    Expected shape::

        {
          "name": "...", "category": "...", "city": "...", "phone": "...",
          "website": "https://...",            # optional
          "hours": "Mon-Fri 8am-6pm",          # optional
          "offers_free_estimates": false,      # optional, default false
          "rating_summary": {"average": 4.6, "count": 40, "platform": "Google"},
          "country": "US",                     # optional ISO code
          "legal": {"impressum": "...", "privacy": "https://..."},  # optional
          "leads": {"endpoint": "https://...", "email": "...",
                    "callback_windows": ["Morning", "Afternoon", "Evening"]},  # optional
          "booking": {"provider": "calcom", "url": "https://cal.com/..."},  # optional
          "logo": {"src": "assets/logo.png", "alt": "..."},   # optional
          "photos": [                          # optional but PREFERRED
            {"src": "photos/roof-1.jpg",
             "alt": "New architectural shingles on a two-storey home",
             "caption": "Full tear-off and re-shingle in West Asheville"},
            {"src": "https://example.com/crew.jpg", "alt": "..."}
          ],
          "reviews": [
            {"author": "...", "rating": 5, "text": "...", "date": "2026-03-01",
             "source_url": "https://..."},
            ...
          ]
        }

    ``photos`` take local paths (absolute, or relative to the working
    directory) or URLs. Local files are copied into the output directory at
    build time; URLs are referenced as-is.

    The business controls the input, so there is no scraping and nothing to
    abuse. Reviews must be ones the business has the right to republish.
    """

    def __init__(self, path: str):
        self.path = path

    def load(self) -> Business:
        with open(self.path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("business JSON must be an object at the top level")
        business = _business_from_dict(data)
        # Resolve relative photo/logo paths against the JSON file's own
        # directory so a business file can ship its images next to it.
        base = os.path.dirname(os.path.abspath(self.path))
        local = list(business.photos)
        if business.logo is not None:
            local.append(business.logo)
        for photo in local:
            if photo.src.startswith(("http://", "https://", "data:")):
                continue
            if os.path.isabs(photo.src):
                continue
            candidate = os.path.join(base, photo.src)
            if os.path.exists(candidate):
                photo.src = candidate
        return business

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Business:
        """Convenience for tests / in-memory use."""
        return _business_from_dict(data)
