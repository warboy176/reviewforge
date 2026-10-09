import os
import tempfile

import pytest

from reviewforge.chat_render import (
    chat_config,
    chat_enabled,
    render_chat_block,
    render_lead_form,
    write_chat_assets,
    chat_js_source,
    chat_css_source,
)
from reviewforge.generator import generate_site_content
from reviewforge.sources import ManualSource


OFFLINE_ENDPOINT = "http://127.0.0.1:1"  # nothing listens here -> fallback

BASE_BUSINESS = {
    "name": "Blue Line Plumbing",
    "category": "Plumber",
    "city": "Boise, ID",
    "phone": "(208) 555-0199",
    "reviews": [
        {"author": "Marcus D.", "rating": 5, "text": "Honest people, fixed our leak fast and cleaned up every nail."},
        {"author": "Priya S.", "rating": 5, "text": "Replaced our entire roof in two days with a clear, no-surprises estimate."},
        {"author": "Greg T.", "rating": 4, "text": "Good quality work on a tricky metal roof repair, fair price."},
    ],
}

LEADS = {"endpoint": "https://leads.example/api/lead", "email": "owner@bluelineplumbing.example"}

def _cfg(html_text):
    tag = '<script type="application/json" id="rf-chat-config">'
    start = html_text.index(tag) + len(tag)
    end = html_text.index('</script>', start)
    return __import__('json').loads(html_text[start:end])

def test_no_leads():
    data = BASE_BUSINESS.copy()
    b = ManualSource.from_dict(data)
    content = generate_site_content(b, endpoint=OFFLINE_ENDPOINT, timeout=2.0)
    
    assert chat_enabled(content) is False
    assert render_chat_block(content) == ""
    assert render_lead_form(content) == ""
    assert chat_config(content) is None
    
    with tempfile.TemporaryDirectory() as tmpdir:
        result = write_chat_assets(content, tmpdir)
        assert result == {}
        assert not os.path.exists(os.path.join(tmpdir, "chat.js"))

def test_with_leads():
    data = BASE_BUSINESS.copy()
    data["leads"] = LEADS
    b = ManualSource.from_dict(data)
    content = generate_site_content(b, endpoint=OFFLINE_ENDPOINT, timeout=2.0)
    
    assert chat_enabled(content) is True
    
    block = render_chat_block(content)
    assert '<script src="chat.js" defer></script>' in block
    assert 'id="rf-chat-css"' in block
    assert ".rfc-launcher" in block
    
    cfg = chat_config(content)
    assert cfg["business"] == "Blue Line Plumbing"
    assert cfg["tel"] == "tel:2085550199"
    assert cfg["endpoint"] == "https://leads.example/api/lead"
    assert cfg["email"] == "owner@bluelineplumbing.example"
    assert cfg["callback_windows"] == ["Morning", "Afternoon", "Evening"]
    assert cfg["booking"] is None
    assert cfg["min_seconds"] == 3
    assert cfg["services"] == [s.title for s in content.services if s.title.strip()]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        result = write_chat_assets(content, tmpdir)
        assert "chat_js" in result
        assert os.path.exists(result["chat_js"])
        
        with open(result["chat_js"], "r", encoding="utf-8") as f:
            js_content = f.read()
            assert "Automated assistant" in js_content

def test_stale_chat_js_removed():
    data = BASE_BUSINESS.copy()
    b = ManualSource.from_dict(data)
    content = generate_site_content(b, endpoint=OFFLINE_ENDPOINT, timeout=2.0)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a stale chat.js file
        stale_path = os.path.join(tmpdir, "chat.js")
        with open(stale_path, "w") as f:
            f.write("stale content")
        
        assert os.path.exists(stale_path)
        
        result = write_chat_assets(content, tmpdir)
        assert result == {}
        assert not os.path.exists(stale_path)

def test_booking_config():
    data = BASE_BUSINESS.copy()
    data["leads"] = LEADS
    data["booking"] = {"provider": "calcom", "url": "https://cal.com/example-plumbing"}
    b = ManualSource.from_dict(data)
    content = generate_site_content(b, endpoint=OFFLINE_ENDPOINT, timeout=2.0)
    
    cfg = chat_config(content)
    assert cfg["booking"]["provider"] == "calcom"
    assert cfg["booking"]["url"] == "https://cal.com/example-plumbing"
    assert cfg["booking"]["label"] == "Cal.com"

def test_consent_de():
    data = BASE_BUSINESS.copy()
    data["country"] = "DE"
    data["legal"] = {"impressum": "Musterstrasse 1, Berlin", "privacy": "https://bluelineplumbing.example/datenschutz"}
    data["leads"] = LEADS
    b = ManualSource.from_dict(data)
    content = generate_site_content(b, endpoint=OFFLINE_ENDPOINT, timeout=2.0)
    
    cfg = chat_config(content)
    assert cfg["consent_required"] is True
    assert cfg["privacy_url"] == "https://bluelineplumbing.example/datenschutz"
    
    form = render_lead_form(content)
    assert 'name="consent" value="yes" required' in form
    assert 'href="https://bluelineplumbing.example/datenschutz"' in form

def test_consent_us_no_privacy():
    data = BASE_BUSINESS.copy()
    data["country"] = "US"
    data["leads"] = LEADS
    b = ManualSource.from_dict(data)
    content = generate_site_content(b, endpoint=OFFLINE_ENDPOINT, timeout=2.0)
    
    cfg = chat_config(content)
    assert cfg["consent_required"] is False
    
    form = render_lead_form(content)
    assert 'name="consent" value="yes">' in form
    assert 'name="consent" value="yes" required' not in form

def test_privacy_text():
    data = BASE_BUSINESS.copy()
    data["legal"] = {"privacy": "Privacy policy"}
    data["leads"] = LEADS
    b = ManualSource.from_dict(data)
    content = generate_site_content(b, endpoint=OFFLINE_ENDPOINT, timeout=2.0)
    
    cfg = chat_config(content)
    assert cfg["consent_required"] is True
    assert cfg["privacy_url"] == "#legal-privacy"
    
    form = render_lead_form(content)
    assert 'href="#legal-privacy"' in form

def test_form_action_email_only():
    data = BASE_BUSINESS.copy()
    data["leads"] = {"email": "owner@bluelineplumbing.example"}
    b = ManualSource.from_dict(data)
    content = generate_site_content(b, endpoint=OFFLINE_ENDPOINT, timeout=2.0)
    
    form = render_lead_form(content)
    assert 'action="mailto:owner@bluelineplumbing.example"' in form
    assert 'enctype="text/plain"' in form

def test_form_action_endpoint():
    data = BASE_BUSINESS.copy()
    data["leads"] = LEADS
    b = ManualSource.from_dict(data)
    content = generate_site_content(b, endpoint=OFFLINE_ENDPOINT, timeout=2.0)
    
    form = render_lead_form(content)
    assert 'action="https://leads.example/api/lead"' in form
    assert 'name="hp_fax"' in form

def test_escaping():
    data = BASE_BUSINESS.copy()
    data["name"] = "Bob </script><script>alert(1)</script>"
    data["leads"] = LEADS
    b = ManualSource.from_dict(data)
    content = generate_site_content(b, endpoint=OFFLINE_ENDPOINT, timeout=2.0)
    
    block = render_chat_block(content)
    # Ensure no "</script><script>" in the JSON
    assert "</script><script>" not in block
    
    cfg = _cfg(block)
    assert cfg["business"] == "Bob </script><script>alert(1)</script>"
    
    form = render_lead_form(content)
    assert "&lt;/script&gt;" in form

def test_assets_sources():
    assert "Automated assistant" in chat_js_source()
    assert ".rfc-launcher" in chat_css_source()

def test_something_else_option():
    data = BASE_BUSINESS.copy()
    data["leads"] = LEADS
    b = ManualSource.from_dict(data)
    content = generate_site_content(b, endpoint=OFFLINE_ENDPOINT, timeout=2.0)
    
    form = render_lead_form(content)
    assert '<option value="Something else">Something else</option>' in form
