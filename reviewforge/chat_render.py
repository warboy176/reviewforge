"""Lead-capture chat widget: everything a page needs, behind one injection point.

render_chat_block() returns the single snippet a template inserts before </body>
(inline CSS, the JSON config and <script src="chat.js" defer>); render_lead_form()
returns the no-JavaScript fallback form for the contact section. Both are empty
unless business.json has a "leads" block.
"""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from reviewforge.leads import consent_required

if TYPE_CHECKING:
    from reviewforge.generator import SiteContent

ASSET_DIR = Path(__file__).resolve().parent / "assets"
CHAT_JS_NAME = "chat.js"
BOOKING_LABELS = {"calcom": "Cal.com", "google": "Google Calendar", "calendly": "Calendly"}
MIN_SECONDS = 3
LEAD_FORM_CSS = """\
.rf-lead-form {
  padding: 20px;
  border: 1px solid var(--border, #d7dee8);
  border-radius: var(--radius, 12px);
  background: var(--bg, #fff);
}
.rf-lead-form label {
  display: block;
  font-weight: 600;
  margin-top: 10px;
}
.rf-lead-form input,
.rf-lead-form select,
.rf-lead-form textarea {
  width: 100%;
  font: inherit;
  padding: 10px;
  border: 1px solid var(--border, #d7dee8);
  border-radius: 8px;
}
.rf-lead-form .rf-check {
  display: flex;
  gap: 8px;
  font-weight: 400;
}
.rf-lead-form .rf-check input {
  width: 20px;
  height: 20px;
  flex: none;
  margin-top: 3px;
}
.rf-lead-form .rf-hp {
  position: absolute;
  left: -10000px;
  width: 1px;
  height: 1px;
  overflow: hidden;
}
.rf-lead-form button {
  background: var(--accent, #e8a13a);
  border: 0;
  border-radius: 999px;
  padding: 12px 22px;
  font-weight: 700;
  margin-top: 14px;
  cursor: pointer;
}
.rf-lead-note {
  font-size: small;
  color: var(--muted, #55617a);
}
"""

def _tel_href(phone) -> str:
    digits = re.sub(r"[^0-9+]", "", phone or "")
    return "tel:" + digits if digits else "#contact"

def _privacy_href(business) -> Optional[str]:
    value = (business.legal.privacy or "").strip()
    if not value:
        return None
    if value.lower().startswith(("http://", "https://")):
        return value
    return "#legal-privacy"

def chat_enabled(content) -> bool:
    return content.business.leads is not None

def chat_config(content) -> Optional[dict]:
    if not chat_enabled(content):
        return None
    
    leads = content.business.leads
    business = content.business
    
    cfg = {
        "business": business.name,
        "phone": business.phone,
        "tel": _tel_href(business.phone),
        "services": [s.title for s in content.services if s.title.strip()],
        "endpoint": leads.endpoint or None,
        "email": leads.email or None,
        "callback_windows": list(leads.callback_windows),
        "booking": None,
        "consent_required": consent_required(business.country, business.legal.privacy),
        "privacy_url": _privacy_href(business),
        "min_seconds": MIN_SECONDS
    }
    
    if business.booking:
        b = business.booking
        cfg["booking"] = {
            "provider": b.provider,
            "url": b.url,
            "label": BOOKING_LABELS[b.provider]
        }
    
    return cfg

def chat_js_source() -> str:
    return (ASSET_DIR / CHAT_JS_NAME).read_text(encoding="utf-8")

def chat_css_source() -> str:
    return (ASSET_DIR / "chat.css").read_text(encoding="utf-8")

def render_chat_block(content) -> str:
    if not chat_enabled(content):
        return ""
    
    cfg = chat_config(content)
    return (
        '<style id="rf-chat-css">\n' +
        chat_css_source() +
        LEAD_FORM_CSS +
        '\n</style>\n' +
        '<script type="application/json" id="rf-chat-config">' +
        json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/") +
        '</script>\n' +
        '<script src="chat.js" defer></script>\n'
    )

def render_lead_form(content) -> str:
    if not chat_enabled(content):
        return ""
    
    leads = content.business.leads
    business = content.business
    
    endpoint = leads.endpoint
    email = leads.email
    
    if endpoint:
        form_action = endpoint
    elif email:
        form_action = f"mailto:{email}"
        enctype = "text/plain"
    else:
        return ""
    
    # Escape all dynamic values
    escaped_business_name = html.escape(business.name, quote=True)
    escaped_phone = html.escape(business.phone, quote=True)
    escaped_endpoint = html.escape(form_action, quote=True)
    escaped_email = html.escape(email, quote=True) if email else ""
    escaped_privacy_url = html.escape(_privacy_href(business) or "", quote=True)
    
    # Build form
    form_html = []
    form_html.append('<form class="rf-lead-form" method="post"')
    if endpoint:
        form_html.append(f' action="{escaped_endpoint}"')
    elif email:
        form_html.append(f' action="mailto:{escaped_email}" enctype="{enctype}"')
    form_html.append(' accept-charset="utf-8">')
    
    form_html.append('<h3 id="rf-lead-h">Request a callback</h3>')
    form_html.append(f'<p class="rf-lead-note">This form sends your details to {escaped_business_name} so it can call you back.</p>')
    
    # Service selection
    form_html.append('<label>What do you need help with? <select name="service">')
    for service in content.services:
        title = service.title.strip()
        if title:
            form_html.append(f'<option value="{html.escape(title, quote=True)}">{html.escape(title, quote=True)}</option>')
    form_html.append('<option value="Something else">Something else</option>')
    form_html.append('</select></label>')
    
    # Name
    form_html.append('<label>Name <input name="name" autocomplete="name" maxlength="80" required></label>')
    
    # Phone
    form_html.append('<label>Phone <input type="tel" name="phone" autocomplete="tel" required></label>')
    
    # Email (optional)
    form_html.append('<label>Email (optional) <input type="email" name="email" autocomplete="email"></label>')
    
    # Callback window
    form_html.append('<label>Best time for a call <select name="callback_window">')
    for window in leads.callback_windows:
        form_html.append(f'<option value="{html.escape(window, quote=True)}">{html.escape(window, quote=True)}</option>')
    form_html.append('</select></label>')
    
    # Message (optional)
    form_html.append('<label>Anything else? (optional) <textarea name="message" maxlength="500" rows="3"></textarea></label>')
    
    # Honeypot
    form_html.append('<div class="rf-hp" aria-hidden="true"><label>Fax <input name="hp_fax" tabindex="-1" autocomplete="off"></label></div>')
    
    # Consent
    consent_required_flag = consent_required(business.country, business.legal.privacy)
    required_attr = ' required' if consent_required_flag else ''
    form_html.append('<label class="rf-check"><input type="checkbox" name="consent" value="yes"' + required_attr + '> I agree that ' + escaped_business_name + ' may use these details to contact me about this request.')
    
    if escaped_privacy_url:
        form_html.append(' <a href="' + escaped_privacy_url + '">Privacy policy</a>')
    
    form_html.append('</label>')
    
    # Hidden fields
    form_html.append('<input type="hidden" name="form" value="nojs">')
    
    # Submit button
    form_html.append('<button type="submit">Send request</button>')
    form_html.append('</form>')
    
    return ''.join(form_html)

def write_chat_assets(content, out_dir) -> dict:
    if chat_enabled(content):
        js_path = os.path.join(out_dir, CHAT_JS_NAME)
        with open(js_path, "w", encoding="utf-8") as f:
            f.write(chat_js_source())
        return {"chat_js": js_path}
    else:
        # Remove stale chat.js if exists
        js_path = os.path.join(out_dir, CHAT_JS_NAME)
        if os.path.exists(js_path):
            os.remove(js_path)
        return {}
