import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Skip node tests if node is not available
node_available = shutil.which("node") is not None
skip_node = pytest.mark.skipif(not node_available, reason="node not available")

# Path to the chat.js file
chat_js_path = Path(__file__).resolve().parent.parent / "reviewforge" / "assets" / "chat.js"


def _node(expr_js):
    """Run a JavaScript expression in node and return the parsed JSON result."""
    script_path = str(chat_js_path.resolve())
    cmd = [
        "node", "-e",
        f"const m = require({json.dumps(script_path)}); process.stdout.write(JSON.stringify({expr_js}));"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
    return json.loads(result.stdout)


@skip_node
def test_booking_prefill_url():
    """Test bookingPrefillUrl parity with Python booking_prefill_url."""
    from reviewforge.leads import booking_prefill_url
    
    test_cases = [
        ("calcom", "https://cal.com/example-plumbing", "Ana R", "ana@example.com", "Leak & drip"),
        ("calendly", "https://calendly.com/example", "Ana R", "ana@example.com", "x"),
        ("google", "https://calendar.app.google/abc123", "Ana", "a@b.example", "x"),
        ("calcom", "https://cal.com/x?month=2026-10&name=old", "New", "", ""),
        ("calcom", "https://cal.com/x#top", "Zoë Müller", "z@example.com", "Ölheizung + Boiler/Tank"),
        ("calendly", "https://calendly.com/e?a=1", "", "", ""),
        ("calcom", "https://cal.com/x?name=old&month=2026-10", "New", "", ""),
    ]
    
    for provider, url, name, email, notes in test_cases:
        js_result = _node(f"m.bookingPrefillUrl({json.dumps(provider)}, {json.dumps(url)}, {json.dumps(name)}, {json.dumps(email)}, {json.dumps(notes)})")
        py_result = booking_prefill_url(provider, url, name, email, notes)
        assert js_result == py_result


@skip_node
def test_valid_phone_and_email():
    """Test validPhone and validEmail parity with Python valid_phone/valid_email."""
    from reviewforge.leads import valid_phone, valid_email
    
    samples = [
        "(208) 555-0199",
        "+49 30 1234567",
        "12345",
        "555-abc-1234",
        "++4930123456",
        "",
        "a@b.co",
        "a@b",
        "a b@c.de"
    ]
    
    for sample in samples:
        js_email_valid = _node(f"m.validEmail({json.dumps(sample)})")
        py_email_valid = valid_email(sample)
        assert js_email_valid == py_email_valid
        
        js_phone_valid = _node(f"m.validPhone({json.dumps(sample)})")
        py_phone_valid = valid_phone(sample)
        assert js_phone_valid == py_phone_valid


@skip_node
def test_build_payload():
    """Test buildPayload returns correct structure."""
    from reviewforge.leads import lead_payload_fields
    
    state = {
        "name": "John Doe",
        "phone": "123-456-7890",
        "email": "john@example.com",
        "service": "Plumbing",
        "message": "Leaky faucet",
        "mode": "callback",
        "window": "Morning",
        "consent": True,
        "hp": "12345"
    }
    
    cfg_callback = {
        "booking": {"provider": "calcom"}
    }
    
    payload = _node(f"m.buildPayload({json.dumps(state)}, {json.dumps(cfg_callback)}, 'http://example.com', 1000, 6000)")
    
    # Check that it has exactly the expected keys
    expected_keys = set(lead_payload_fields()) | {"hp_fax", "elapsed_ms"}
    assert set(payload.keys()) == expected_keys
    
    # Check specific values for callback mode
    assert payload["name"] == "John Doe"
    assert payload["phone"] == "123-456-7890"
    assert payload["email"] == "john@example.com"
    assert payload["service"] == "Plumbing"
    assert payload["callback_window"] == "Morning"
    assert payload["booking_provider"] == ""
    assert payload["message"] == "Leaky faucet"
    assert payload["consent"] is True
    assert payload["hp_fax"] == "12345"
    assert payload["elapsed_ms"] == 5000
    
    # Test booking mode
    state_booking = {
        "name": "John Doe",
        "phone": "123-456-7890",
        "email": "john@example.com",
        "service": "Plumbing",
        "message": "Leaky faucet",
        "mode": "booking",
        "window": "",
        "consent": True,
        "hp": "12345"
    }
    
    cfg_booking = {
        "booking": {"provider": "calcom"}
    }
    
    payload_booking = _node(f"m.buildPayload({json.dumps(state_booking)}, {json.dumps(cfg_booking)}, 'http://example.com', 1000, 6000)")
    
    # Check specific values for booking mode
    assert payload_booking["name"] == "John Doe"
    assert payload_booking["phone"] == "123-456-7890"
    assert payload_booking["email"] == "john@example.com"
    assert payload_booking["service"] == "Plumbing"
    assert payload_booking["callback_window"] == ""
    assert payload_booking["booking_provider"] == "calcom"
    assert payload_booking["message"] == "Leaky faucet"
    assert payload_booking["consent"] is True
    assert payload_booking["hp_fax"] == "12345"
    assert payload_booking["elapsed_ms"] == 5000


@skip_node
def test_mailto_href():
    """Test mailtoHref produces correct format."""
    email = "owner@x.example"
    business = "Test Business"
    
    # Test booking payload
    payload = {
        "name": "John Doe",
        "phone": "123-456-7890",
        "email": "john@example.com",
        "service": "Plumbing",
        "callback_window": "",
        "booking_provider": "calcom",
        "message": "Leaky faucet",
        "consent": True,
        "page_url": "http://example.com"
    }
    
    href = _node(f"m.mailtoHref({json.dumps(email)}, {json.dumps(business)}, {json.dumps(payload)})")
    
    assert href.startswith("mailto:owner@x.example?subject=")
    assert "Consent%20to%20be%20contacted%3A%20yes" in href
    assert "Booking%3A%20calcom" in href
    
    # Test empty email doesn't produce Email line
    payload_empty_email = {
        "name": "John Doe",
        "phone": "123-456-7890",
        "email": "",
        "service": "Plumbing",
        "callback_window": "",
        "booking_provider": "calcom",
        "message": "Leaky faucet",
        "consent": True,
        "page_url": "http://example.com"
    }
    
    href_empty_email = _node(f"m.mailtoHref({json.dumps(email)}, {json.dumps(business)}, {json.dumps(payload_empty_email)})")
    
    assert "Email%3A" not in href_empty_email


def test_static_file_integrity():
    """Static tests for the chat.js file."""
    # Read the file
    with open(chat_js_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # File size check
    assert len(chat_js_path.read_bytes()) < 15 * 1024, "chat.js exceeds the 15 KB target"
    
    # Contains required strings
    assert "Automated assistant" in content
    assert 'role' in content
    assert '"dialog"' in content or 'dialog' in content
    assert "aria-live" in content
    assert "rfc-consent" in content
    assert "hpInput.value" in content
    
    # Does NOT contain forbidden strings
    forbidden = [
        "innerHTML", "insertAdjacentHTML", "eval(", "localStorage",
        "document.cookie", "http://", "https://"
    ]
    
    for forbidden_str in forbidden:
        assert forbidden_str not in content, f"Forbidden string '{forbidden_str}' found in file"
    
    # Does NOT contain "price" outside of the allowed sentence
    allowed_sentence = "I can't answer questions about prices or availability."
    content_no_allowed = content.replace(allowed_sentence, "")
    assert "price" not in content_no_allowed.lower(), "Found 'price' outside of allowed sentence"
