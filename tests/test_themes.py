import pytest

from reviewforge.themes import (
    PALETTES,
    PALETTE_TOKENS,
    PALETTE_LABELS,
    DEFAULT_PALETTE,
    _ALIASES,
    _RULES,
    normalize_palette,
    palette_for,
    palette_css,
    render_astra_css,
    ASTRA_EXTRA_CSS,
    astra_css_source,
)
from reviewforge.sources import ManualSource


def test_palettes_structure():
    assert set(PALETTES) == {"roofing", "plumbing", "electrical", "landscaping", "cleaning", "auto"}
    assert PALETTE_TOKENS == ("brand", "brand-ink", "accent", "accent-ink", "surface", "surface-alt", "ink", "muted", "line")
    
    for name, palette in PALETTES.items():
        assert set(palette.keys()) == set(PALETTE_TOKENS)
        for value in palette.values():
            assert isinstance(value, str)
            assert value.startswith("#")
            assert len(value) == 7
            assert all(c in "0123456789abcdef" for c in value[1:])
    
    # Specific values
    assert PALETTES["plumbing"]["brand"] == "#175a69"
    assert PALETTES["roofing"]["brand"] == "#713b2f"
    assert all(palette["brand-ink"] == "#ffffff" for palette in PALETTES.values())


def test_palette_for_mapping():
    test_cases = [
        ("Roofing Contractor", "roofing"),
        ("Gutter installer", "roofing"),
        ("Dachdecker", "roofing"),
        ("Plumber", "plumbing"),
        ("Plumbing & Heating", "plumbing"),
        ("Drain cleaning", "plumbing"),
        ("Electrician", "electrical"),
        ("Elektriker", "electrical"),
        ("Solar installer", "electrical"),
        ("Landscaping", "landscaping"),
        ("Lawn care service", "landscaping"),
        ("Tree service", "landscaping"),
        ("House Cleaning Service", "cleaning"),
        ("Carpet cleaning", "cleaning"),
        ("Gebäudereinigung", "cleaning"),
        ("Auto Repair Shop", "auto"),
        ("Car mechanic", "auto"),
        ("Tire shop", "auto"),
        ("Kfz-Werkstatt", "auto"),
    ]
    
    for category, expected in test_cases:
        assert palette_for(category) == expected


def test_palette_for_default():
    assert palette_for("Bakery") == DEFAULT_PALETTE
    assert palette_for("Carpentry") == DEFAULT_PALETTE
    assert palette_for("Cartography") == DEFAULT_PALETTE
    assert palette_for("") == DEFAULT_PALETTE
    assert palette_for(None) == DEFAULT_PALETTE


def test_palette_for_override():
    assert palette_for("Plumber", "auto") == "auto"
    assert palette_for("Plumber", " Roofing ") == "roofing"
    assert palette_for("Bakery", "auto repair") == "auto"
    assert palette_for("Plumber", None) == "plumbing"
    assert palette_for("Plumber", "") == "plumbing"


def test_normalize_palette():
    assert normalize_palette(None) is None
    assert normalize_palette("") is None
    assert normalize_palette("  ") is None
    assert normalize_palette("roofing") == "roofing"
    assert normalize_palette("ROOFING") == "roofing"
    assert normalize_palette("roof") == "roofing"
    assert normalize_palette("plumber") == "plumbing"
    assert normalize_palette("electrician") == "electrical"
    assert normalize_palette("landscaper") == "landscaping"
    
    with pytest.raises(ValueError, match="'palette' must be a string"):
        normalize_palette(5)
    
    with pytest.raises(ValueError, match="'palette' must be one of: auto, cleaning, electrical, landscaping, plumbing, roofing"):
        normalize_palette("neon")


def test_palette_css():
    css = palette_css("plumbing")
    assert css.startswith("/* Palette: Plumbing")
    assert ":root {" in css
    assert "  --brand: #175a69;\n" in css
    for token in PALETTE_TOKENS:
        assert f"--{token}: " in css
    with pytest.raises(ValueError, match="Unknown palette"):
        palette_css("neon")


def test_render_astra_css():
    css = render_astra_css("plumbing")
    assert ".site-header" in css
    assert ".mobile-call-bar" in css
    assert "--bg: var(--surface)" in css
    assert "--border: var(--line)" in css
    brand_index = css.rindex("--brand: #175a69;")
    call_bar_index = css.rindex(".mobile-call-bar")
    assert brand_index > call_bar_index
    assert "@import" not in css
    assert "url(" not in css
    assert "http" not in css


def test_astra_css_source():
    css = astra_css_source()
    assert ".site-header" in css and ".mobile-call-bar" in css
    assert "@import" not in css
    assert "url(" not in css
    assert "http" not in css


def test_astra_extra_css():
    # Check that braces are balanced
    assert ASTRA_EXTRA_CSS.count("{") == ASTRA_EXTRA_CSS.count("}")
    assert "body .rfc-launcher" in ASTRA_EXTRA_CSS
    assert "/* ReviewForge integration:" in ASTRA_EXTRA_CSS


def test_manual_source_palette_field():
    # With valid palette
    b = ManualSource.from_dict({
        "name": "A",
        "category": "Plumber",
        "city": "Boise, ID",
        "phone": "(208) 555-0100",
        "palette": "Electrical"
    })
    assert b.palette == "electrical"

    # Without palette key
    b = ManualSource.from_dict({
        "name": "A",
        "category": "Plumber",
        "city": "Boise, ID",
        "phone": "(208) 555-0100"
    })
    assert b.palette is None

    # With invalid palette
    with pytest.raises(ValueError, match="palette"):
        ManualSource.from_dict({
            "name": "A",
            "category": "Plumber",
            "city": "Boise, ID",
            "phone": "(208) 555-0100",
            "palette": "neon"
        })
