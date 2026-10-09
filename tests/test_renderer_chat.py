"""Tests for the chat widget integration in the renderer."""
import os
import re

from reviewforge.sources import ManualSource
from reviewforge.generator import generate_site_content
from reviewforge.renderer import render_html, write_site

OFFLINE_ENDPOINT = "http://127.0.0.1:1"  # nothing listens here -> fallback

BASE_CONTENT = {
    "name": "Blue Line Plumbing",
    "category": "Plumber",
    "city": "Boise, ID",
    "phone": "(208) 555-0199",
    "website": "https://bluelineplumbing.example",
    "reviews": [
        {"author": "Alice B.", "rating": 5, "text": "Great service, fixed my leak fast."},
        {"author": "Charlie D.", "rating": 5, "text": "Professional and clean work."},
        {"author": "Dana E.", "rating": 4, "text": "Good value for the job done."},
    ],
}


def _content(**extra):
    data = dict(BASE_CONTENT, **extra)
    b = ManualSource.from_dict(data)
    return b, generate_site_content(b, endpoint=OFFLINE_ENDPOINT, timeout=2.0)


def test_render_without_leads():
    b, content = _content()
    doc = render_html(content)
    
    # No chat assets should be present
    assert "chat.js" not in doc
    assert "rf-chat-config" not in doc
    assert "rf-lead-form" not in doc
    assert "<script src" not in doc
    
    # Provenance script should still be there
    assert "reviewforge-provenance" in doc


def test_render_with_leads():
    b, content = _content(leads={"endpoint": "https://leads.example/api/lead"})
    doc = render_html(content)
    
    # Should contain the chat script
    assert doc.count('<script src="chat.js" defer>') == 1
    
    # Config script should be between </footer> and </body>
    footer_pos = doc.rfind("</footer>")
    body_pos = doc.rfind("</body>")
    config_pos = doc.find('<script type="application/json" id="rf-chat-config">')
    
    assert footer_pos < config_pos < body_pos
    
    # Lead form should be in contact section
    contact_pos = doc.find('id="contact"')
    lead_form_pos = doc.find('class="rf-lead-form"')
    main_pos = doc.find("</main>")
    
    assert contact_pos < lead_form_pos < main_pos
    
    # No trackers
    assert "google-analytics" not in doc
    assert "gtag(" not in doc
    assert "facebook" not in doc
    assert '<script src="http' not in doc
    
    # Provenance script should still be there
    assert "reviewforge-provenance" in doc


def test_render_with_de_consent():
    b, content = _content(
        country="DE",
        legal={"impressum": "Musterstrasse 1, 10115 Berlin", "privacy": "https://bluelineplumbing.example/datenschutz"},
        leads={"endpoint": "https://leads.example/api/lead"}
    )
    doc = render_html(content)
    
    # Consent checkbox should be required
    assert 'name="consent" value="yes" required' in doc
    
    # Config JSON should have consent_required: true
    config_start = doc.find('<script type="application/json" id="rf-chat-config">')
    config_end = doc.find('</script>', config_start)
    config_json = doc[config_start + 58:config_end]
    
    assert '"consent_required": true' in config_json


def test_render_with_us_no_privacy():
    b, content = _content(
        country="US",
        leads={"endpoint": "https://leads.example/api/lead"}
    )
    doc = render_html(content)
    
    # Config JSON should have consent_required: false
    config_start = doc.find('<script type="application/json" id="rf-chat-config">')
    config_end = doc.find('</script>', config_start)
    config_json = doc[config_start + 58:config_end]
    
    assert '"consent_required": false' in config_json


def test_write_site_with_leads(tmp_path):
    b, content = _content(leads={"endpoint": "https://leads.example/api/lead"})
    paths = write_site(content, str(tmp_path / "out"))
    
    # Should return chat_js key
    assert "chat_js" in paths
    
    # chat.js file should exist and be under 15000 bytes
    js_path = paths["chat_js"]
    assert os.path.exists(js_path)
    
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()
    
    assert len(js_content.encode("utf-8")) < 15 * 1024
    assert "Automated assistant" in js_content
    
    # Provenance script should still be there
    html = open(paths["index"], encoding="utf-8").read()
    assert "reviewforge-provenance" in html
