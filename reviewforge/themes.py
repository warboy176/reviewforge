"""Design themes: the Astra stylesheet, its six trade palettes, and the
category -> palette mapping. Theming is done only with CSS custom properties:
the palette is a :root block appended after the stylesheet, so it overrides
the stylesheet's built-in (roofing) values.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

ASSET_DIR = Path(__file__).resolve().parent / "assets"
THEMES = ("astra", "classic")
DEFAULT_THEME = "astra"

PALETTE_TOKENS = ("brand", "brand-ink", "accent", "accent-ink", "surface", "surface-alt", "ink", "muted", "line")

PALETTES = {
    "roofing": {
        "brand": "#713b2f",
        "brand-ink": "#ffffff",
        "accent": "#f2d5b4",
        "accent-ink": "#272722",
        "surface": "#fcf8f3",
        "surface-alt": "#f1e8df",
        "ink": "#272722",
        "muted": "#595950",
        "line": "#d8cbc0",
    },
    "plumbing": {
        "brand": "#175a69",
        "brand-ink": "#ffffff",
        "accent": "#d4ebe9",
        "accent-ink": "#202e31",
        "surface": "#f7faf9",
        "surface-alt": "#e8f0ee",
        "ink": "#202e31",
        "muted": "#506164",
        "line": "#c7d8d5",
    },
    "electrical": {
        "brand": "#514322",
        "brand-ink": "#ffffff",
        "accent": "#f0d36a",
        "accent-ink": "#2d2a21",
        "surface": "#fcfaf3",
        "surface-alt": "#f2ecdd",
        "ink": "#2d2a21",
        "muted": "#625d4b",
        "line": "#d9cfb8",
    },
    "landscaping": {
        "brand": "#345441",
        "brand-ink": "#ffffff",
        "accent": "#dce5b7",
        "accent-ink": "#252e25",
        "surface": "#f9faf3",
        "surface-alt": "#edf0e3",
        "ink": "#252e25",
        "muted": "#566150",
        "line": "#ccd4be",
    },
    "cleaning": {
        "brand": "#425b73",
        "brand-ink": "#ffffff",
        "accent": "#dce8f2",
        "accent-ink": "#252e38",
        "surface": "#fafbfc",
        "surface-alt": "#ecf0f5",
        "ink": "#252e38",
        "muted": "#576371",
        "line": "#cbd4df",
    },
    "auto": {
        "brand": "#553c4a",
        "brand-ink": "#ffffff",
        "accent": "#ecd5ca",
        "accent-ink": "#30272c",
        "surface": "#fcf8f5",
        "surface-alt": "#efe7e3",
        "ink": "#30272c",
        "muted": "#65575f",
        "line": "#d9c9c4",
    },
}

PALETTE_LABELS = {
    "roofing": "Roofing: terracotta and limestone",
    "plumbing": "Plumbing: deep teal and mineral",
    "electrical": "Electrical: bronze and soft voltage yellow",
    "landscaping": "Landscaping: forest and pale leaf",
    "cleaning": "Cleaning: slate blue and porcelain",
    "auto": "Auto repair: oxblood plum and warm alloy",
}

DEFAULT_PALETTE = "cleaning"  # the slate-blue palette is the most neutral one, used when the category matches no trade.

_ALIASES = {
    "auto repair": "auto",
    "auto-repair": "auto",
    "automotive": "auto",
    "roof": "roofing",
    "plumber": "plumbing",
    "electrician": "electrical",
    "landscaper": "landscaping",
}

_RULES = (
    ("roofing", ("roof", "gutter", "shingl", "dachdeck", "bedachung"), ()),
    ("plumbing", ("plumb", "drain", "sewer", "water heater", "septic", "pipe", "heating", "hvac", "sanitär", "sanitaer", "klempner", "installateur"), ()),
    ("electrical", ("electric", "elektr", "solar", "lighting"), ()),
    ("landscaping", ("landscap", "lawn", "garden", "garten", "gärtn", "irrigation", "arborist", "landschaft"), ("tree", "trees", "yard")),
    ("cleaning", ("clean", "maid", "janitor", "pressure wash", "power wash", "carpet", "reinigung"), ()),
    ("auto", ("automotive", "auto repair", "auto body", "mechanic", "collision", "kfz", "autowerkstatt", "body shop"), ("auto", "car", "cars", "tire", "tires", "tyre", "tyres", "vehicle", "vehicles")),
)


def normalize_palette(value) -> Optional[str]:
    original = value
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("'palette' must be a string")
    value = value.strip()
    if not value:
        return None
    value = value.lower()
    value = _ALIASES.get(value, value)
    if value in PALETTES:
        return value
    raise ValueError(f"'palette' must be one of: {', '.join(sorted(PALETTES))} (got {original!r})")


def palette_for(category: str, override: Optional[str] = None) -> str:
    if override is not None:
        norm_override = normalize_palette(override)
        if norm_override is not None:
            return norm_override
    category = category or ""
    lowered = category.lower()
    words = re.findall(r"[a-z0-9]+", lowered)
    for palette, stems, rule_words in _RULES:
        if any(stem in lowered for stem in stems) or any(word in words for word in rule_words):
            return palette
    return DEFAULT_PALETTE


def palette_css(name: str) -> str:
    try:
        label = PALETTE_LABELS[name]
    except KeyError:
        raise ValueError(f"Unknown palette '{name}'")
    return "/* Palette: " + label + " */\n:root {\n" + "".join(f"  --{t}: {PALETTES[name][t]};\n" for t in PALETTE_TOKENS) + "}\n"


def astra_css_source() -> str:
    return (ASSET_DIR / "astra.css").read_text(encoding="utf-8")


ASTRA_EXTRA_CSS = """/* ReviewForge integration: aliases the chat widget and lead form read, so they pick up the palette. */
:root { --bg: var(--surface); --border: var(--line); --brand-dark: var(--brand); --radius: var(--radius-card); }

.brand .logo { inline-size: 11.25rem; max-inline-size: 100%; block-size: 3rem; object-fit: contain; object-position: left center; }

.hero__media { position: relative; }

.photo-credit { position: absolute; z-index: 1; right: 0.75rem; bottom: 0.75rem; max-width: 60%; padding: 0.25rem 0.6rem; border-radius: var(--radius-small); background: rgba(8,20,32,0.82); color: #fff; font-size: 0.75rem; line-height: 1.3; pointer-events: none; }

.work-card__caption .credit { display: block; margin-block-start: var(--space-1); font-size: var(--text-small); }

.section-intro { max-inline-size: var(--reading-width); margin-block-start: var(--space-4); color: var(--muted); }

.review-card__meta { display: block; margin-block-start: var(--space-1); color: var(--muted); font-size: var(--text-small); font-weight: var(--weight-regular); }

.legal-text { max-inline-size: 80ch; margin-block-start: var(--space-6); }
.legal-text h2 { margin-block: var(--space-4) var(--space-1); font-size: var(--text-base); letter-spacing: normal; }
.legal-text p { white-space: pre-line; }

.site-footer__website { margin-block-start: var(--space-2); }

.contact .lead-form-wrap { margin-block-start: var(--space-6); color: var(--ink); }
.contact .rf-lead-form { background: var(--surface); }
.rf-lead-form button { color: var(--accent-ink); }

@media (max-width: 47.999rem) {
  .brand .logo { inline-size: 9rem; block-size: 2.5rem; }
  body .rfc-launcher { bottom: calc(var(--mobile-call-height) + env(safe-area-inset-bottom, 0px) + 0.75rem); }
  /* Phones: the 3rem hero minimum split long words ("replacemen|ts") at 390px; scale with the viewport instead. */
  .hero h1 { font-size: clamp(2rem, 9vw, 3rem); }
  .header-call__number { white-space: nowrap; }
} /* on phones the chat launcher sits above the fixed call bar. */


"""

def render_astra_css(palette: str) -> str:
    return astra_css_source().rstrip("\n") + "\n\n" + ASTRA_EXTRA_CSS.strip("\n") + "\n\n" + palette_css(palette)
