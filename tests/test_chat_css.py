import re
from pathlib import Path

def test_chat_css():
    css_file = Path(__file__).resolve().parent.parent / "reviewforge" / "assets" / "chat.css"
    
    # Read the CSS file
    with open(css_file, 'r', encoding='utf-8') as f:
        css_content = f.read()
    
    # Test 1: File size < 6000 bytes
    assert len(css_content) < 6000, f"CSS file is {len(css_content)} bytes, exceeds 6000 byte limit"
    
    # Test 2: Contains required strings
    assert "prefers-reduced-motion" in css_content
    assert "max-width: 640px" in css_content
    assert "100dvh" in css_content
    
    # Test 3: Contains required CSS variables
    assert "var(--brand" in css_content
    assert "var(--bg" in css_content
    assert "var(--ink" in css_content
    
    # Test 4: No forbidden patterns
    assert "@import" not in css_content
    assert "url(" not in css_content
    assert "http" not in css_content
    
    # Test 5: All required class names present
    expected_classes = {
        ".rfc-launcher", ".rfc-dialog", ".rfc-head", ".rfc-log", ".rfc-msg",
        ".rfc-bot", ".rfc-me", ".rfc-step", ".rfc-chip", ".rfc-primary",
        ".rfc-err", ".rfc-summary", ".rfc-tel", ".rfc-hp"
    }
    
    found_classes = set(re.findall(r'\.rfc-\w+', css_content))
    assert expected_classes.issubset(found_classes), f"Missing classes: {expected_classes - found_classes}"
    
    # Test 6: Braces are balanced
    open_braces = css_content.count('{')
    close_braces = css_content.count('}')
    assert open_braces == close_braces, f"Unbalanced braces: {open_braces} opening, {close_braces} closing"
