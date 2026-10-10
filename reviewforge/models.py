"""Core data models for ReviewForge.

These are deliberately plain dataclasses with no third-party dependencies so
the tool stays auditable and easy to run anywhere.

The image models carry the project's hardest honesty guarantee, and they
enforce it in ``__post_init__`` rather than in documentation: an image that was
not supplied by the business can never end up flagged as the business's own,
and can never carry a caption that implies the business did the work shown.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from reviewforge.leads import BookingConfig, LeadsConfig

# --------------------------------------------------------------------------
# Image provenance vocabulary
# --------------------------------------------------------------------------
#: The business handed us this file / URL. Real photos of real work.
ORIGIN_SUPPLIED = "supplied"
#: Synthesised generic trade imagery. NOT this business's work. Illustrative.
ORIGIN_GENERATED = "generated"

VALID_ORIGINS = (ORIGIN_SUPPLIED, ORIGIN_GENERATED)

#: Origins that genuinely depict the business's own work.
BUSINESS_OWN_ORIGINS = (ORIGIN_SUPPLIED,)

#: Neutral alt text used when an illustrative image has none, or when the
#: supplied alt text made an ownership claim and had to be replaced.
GENERIC_ILLUSTRATIVE_ALT = "Illustrative stock-style photograph of trade work"

# First-person language. On an illustrative image, *any* of this turns a
# decorative picture into a false claim ("our crew", "a job we finished"), so
# the rule is deliberately blunt: no first person on imagery we generated.
_FIRST_PERSON_RE = re.compile(
    r"\b(we|we'?(?:ve|re|ll|d)|us|our|ours|ourselves|i|i'?(?:ve|m|ll|d)|my|mine)\b",
    re.IGNORECASE,
)

# Phrases that claim a specific, real job even without a pronoun.
_OWNERSHIP_CLAIM_RE = re.compile(
    r"""\b(
        recent\s+(?:job|work|project|install(?:ation)?|build|repair)
      | completed\s+(?:job|work|project|install(?:ation)?|repair)
      | finished\s+(?:job|work|project|install(?:ation)?|repair)
      | (?:job|project|work|install(?:ation)?|repair)\s+(?:site|we|completed|finished|done)
      | before\s+and\s+after
      | portfolio
      | past\s+(?:job|work|project|client|customer)s?
      | actual\s+(?:job|work|photo|customer|client)
      | real\s+(?:job|customer|client)
      | this\s+(?:home|house|property|roof|customer|client|job)
      | client'?s?\s+(?:home|house|property|roof)
      | customer'?s?\s+(?:home|house|property|roof)
      | crew\s+(?:on|at)\s+(?:site|a\s+job)
      | workmanship\s+(?:shown|pictured)
      | as\s+(?:seen|pictured)\s+(?:on|at)\s+a\s+(?:job|customer)
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)


def caption_implies_ownership(text: Optional[str]) -> bool:
    """True if ``text`` would read as "this is a job this business did".

    Used to reject captions and alt text on illustrative imagery. Kept
    deliberately over-eager: a wrongly-stripped caption costs a little polish,
    a wrongly-kept one is a lie on a real business's website.
    """
    if not text:
        return False
    clean = " ".join(str(text).split())
    return bool(_FIRST_PERSON_RE.search(clean) or _OWNERSHIP_CLAIM_RE.search(clean))


@dataclass
class SiteImage:
    """One image on the generated site, with enforced provenance.

    ``origin`` is the single source of truth. ``is_business_own`` is *derived*
    from it in ``__post_init__`` and cannot be set to a value that contradicts
    the origin -- so no caller, template or config file can smuggle generated
    imagery onto the page labelled as the business's own work.

    Honesty rules applied on construction when the image is illustrative:
      * a caption implying ownership is dropped (recorded in
        ``rejected_caption`` so ``provenance.json`` shows what was removed);
      * alt text implying ownership is replaced with neutral generic alt text;
      * empty alt text is filled with neutral generic alt text.
    """

    src: str
    alt: str = ""
    caption: Optional[str] = None
    origin: str = ORIGIN_GENERATED
    #: "hero" | "service" | "gallery" | "logo"
    role: str = "gallery"
    width: Optional[int] = None
    height: Optional[int] = None
    #: Photo credit, shown under the photo (e.g. a photographer or licence).
    attribution: Optional[str] = None
    #: Derived -- see __post_init__. Never trust the inbound value.
    is_business_own: bool = False
    #: Set when an ownership-claiming caption was stripped.
    rejected_caption: Optional[str] = None
    #: Set when ownership-claiming alt text was replaced.
    rejected_alt: Optional[str] = None
    #: Free-form generation detail (prompt, model, seed) for provenance.
    generation: Optional[dict] = None

    def __post_init__(self) -> None:
        if self.origin not in VALID_ORIGINS:
            raise ValueError(
                f"image origin {self.origin!r} is not one of {VALID_ORIGINS}"
            )
        if not str(self.src).strip():
            raise ValueError("image src must not be empty")
        self.src = str(self.src).strip()

        # Derived, not declared. This is the whole guarantee.
        self.is_business_own = self.origin in BUSINESS_OWN_ORIGINS

        alt = " ".join(str(self.alt or "").split())
        caption = " ".join(str(self.caption).split()) if self.caption else None

        if self.is_business_own:
            # The business is making its own claim about its own photo. We keep
            # the words it chose -- only normalising whitespace.
            self.alt = alt
            self.caption = caption or None
        else:
            if caption and caption_implies_ownership(caption):
                self.rejected_caption = caption
                caption = None
            if alt and caption_implies_ownership(alt):
                self.rejected_alt = alt
                alt = ""
            self.alt = alt or GENERIC_ILLUSTRATIVE_ALT
            self.caption = caption or None

    @property
    def illustrative(self) -> bool:
        return not self.is_business_own

    def to_provenance(self) -> dict:
        """Auditable record of this one image."""
        rec = {
            "src": self.src,
            "role": self.role,
            "origin": self.origin,
            "is_business_own": self.is_business_own,
            "illustrative": self.illustrative,
            "alt": self.alt,
            "caption": self.caption,
        }
        if self.attribution:
            rec["attribution"] = self.attribution
        if self.rejected_caption:
            rec["rejected_caption"] = self.rejected_caption
            rec["rejected_caption_reason"] = (
                "caption implied the business performed the work shown, but this "
                "image is illustrative"
            )
        if self.rejected_alt:
            rec["rejected_alt"] = self.rejected_alt
            rec["rejected_alt_reason"] = (
                "alt text implied the business performed the work shown, but this "
                "image is illustrative"
            )
        if self.generation:
            rec["generation"] = self.generation
        return rec


@dataclass
class Review:
    """A single real review, exactly as sourced. Never synthesize these."""

    author: str
    rating: float
    text: str
    date: Optional[str] = None
    # Stable id used for the machine-readable provenance note.
    source_index: Optional[int] = None
    #: Optional link to where the review was originally published. Recorded in
    #: provenance.json so anyone can check the quote against its source.
    source_url: Optional[str] = None

    @property
    def stars(self) -> str:
        """Render an integer star string for display (rounded, 1-5)."""
        n = max(0, min(5, int(round(self.rating))))
        return "★" * n + "☆" * (5 - n)


@dataclass
class RatingSummary:
    """The business's overall rating on a named platform, as it reports it.

    Supplied by the business (e.g. "4.6 on Google from 40 reviews"). Without
    it, the page only states the average of the reviews it actually shows, so
    a hand-picked subset can never read as the business's overall rating.
    """

    average: float
    count: int
    platform: str


@dataclass
class LegalInfo:
    """Legal-notice and privacy-policy content. Each is text or an http(s) URL."""

    impressum: Optional[str] = None
    privacy: Optional[str] = None


#: EU/EEA countries where a site operator generally owes visitors a legal
#: notice and a privacy policy. Germany (DE) is enforced as a hard error
#: because the Impressum duty there is explicit and routinely enforced.
EU_COUNTRIES = frozenset(
    "AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO "
    "SE SI SK IS LI NO".split()
)


class LegalRequirementError(ValueError):
    """The business's jurisdiction requires legal pages that were not supplied."""


@dataclass
class Business:
    """A local service business, its real reviews and its real photos."""

    name: str
    category: str
    city: str
    phone: str
    website: Optional[str] = None
    hours: Optional[str] = None
    reviews: list[Review] = field(default_factory=list)
    #: Photos the business supplied (or that came from its own Google Business
    #: Profile). These are the preferred imagery and the only images allowed in
    #: the "our work" gallery.
    photos: list[SiteImage] = field(default_factory=list)
    #: A logo the business supplied. ReviewForge never generates a logo; with
    #: no logo we fall back to a typographic wordmark in the renderer.
    logo: Optional[SiteImage] = None
    #: Only when True may the words "free estimate"/"free quote" (or any
    #: "free" offer) appear anywhere on the page. Default False: ReviewForge
    #: never assumes a business gives anything away.
    offers_free_estimates: bool = False
    #: The overall rating as the business reports it (optional, see class).
    rating_summary: Optional[RatingSummary] = None
    #: ISO 3166-1 alpha-2 country code, e.g. "US", "DE".
    country: Optional[str] = None
    legal: LegalInfo = field(default_factory=LegalInfo)
    #: Optional lead-capture settings for the chat widget (see reviewforge.leads).
    leads: Optional[LeadsConfig] = None
    #: Optional third-party booking page (cal.com / Google / Calendly).
    booking: Optional[BookingConfig] = None
    #: Optional colour palette for the default (Astra) design, one of
    #: reviewforge.themes.PALETTES. None means: pick it from the category.
    palette: Optional[str] = None

    @property
    def rating_average(self) -> Optional[float]:
        if not self.reviews:
            return None
        return round(sum(r.rating for r in self.reviews) / len(self.reviews), 1)

    def legal_warnings(self) -> list[str]:
        """Check the legal pages the jurisdiction needs.

        Raises :class:`LegalRequirementError` for Germany without both an
        Impressum and a privacy policy; returns warnings for other EU/EEA
        countries that are missing either.
        """
        missing = [
            name for name, val in (
                ("impressum", self.legal.impressum),
                ("privacy", self.legal.privacy),
            ) if not (val or "").strip()
        ]
        if not missing or not self.country:
            return []
        if self.country == "DE":
            raise LegalRequirementError(
                "country is DE but legal." + " and legal.".join(missing)
                + " is missing. A German business website needs an Impressum "
                "(legal notice) and a Datenschutzerklaerung (privacy policy); "
                "ReviewForge will not build one without them. Supply each as "
                "text or as a URL under \"legal\" in business.json."
            )
        if self.country in EU_COUNTRIES:
            return [
                f"country is {self.country} (EU/EEA) but legal."
                + " and legal.".join(missing)
                + " is missing; most EU/EEA jurisdictions expect a legal "
                "notice and a privacy policy on a business website."
            ]
        return []

    @property
    def review_count(self) -> int:
        return len(self.reviews)

    @property
    def own_photos(self) -> list[SiteImage]:
        """Only the photos that genuinely belong to this business."""
        return [p for p in self.photos if p.is_business_own]
