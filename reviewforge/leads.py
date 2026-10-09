"""Lead-capture and booking configuration for the optional chat widget.

Pure functions only, no I/O. The browser widget (reviewforge/assets/chat.js)
mirrors booking_prefill_url, valid_phone and valid_email; tests check that the
two implementations agree, so keep these simple and deterministic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit, parse_qsl, quote

DEFAULT_CALLBACK_WINDOWS = ("Morning", "Afternoon", "Evening")
BOOKING_PROVIDERS = ("calcom", "google", "calendly")
PROVIDER_HOSTS = {
    "calcom": ("cal.com",),
    "calendly": ("calendly.com",),
    "google": ("calendar.app.google", "calendar.google.com")
}
PROVIDER_LABELS = {"calcom": "cal.com", "calendly": "calendly.com", "google": "Google Calendar (calendar.app.google / calendar.google.com)"}
MAX_CALLBACK_WINDOWS = 6
MAX_WINDOW_LEN = 40


@dataclass
class LeadsConfig:
    endpoint: Optional[str] = None
    email: Optional[str] = None
    callback_windows: list[str] = field(default_factory=lambda: list(DEFAULT_CALLBACK_WINDOWS))


@dataclass
class BookingConfig:
    provider: str
    url: str
    self_hosted: bool = False


def valid_email(value) -> bool:
    if not value:
        return False
    s = str(value).strip()
    return re.fullmatch(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", s) is not None


def valid_phone(value) -> bool:
    if not value:
        return False
    s = str(value)
    # Remove specified characters: space, "-", "(", ")", ".", "\t", "/"
    cleaned = ""
    i = 0
    if s.startswith("+"):
        cleaned += "+"
        i = 1
    for char in s[i:]:
        if char not in " -().\t/":
            cleaned += char
    # If we started with a "+", drop it from the final string
    if cleaned.startswith("+") and len(cleaned) > 1:
        cleaned = cleaned[1:]
    # Must be all digits and have 6 to 15 digits inclusive
    return bool(re.fullmatch(r"[0-9]{6,15}", cleaned))


def _host_matches(host: str, domains: tuple[str, ...]) -> bool:
    host = host.lower()
    for domain in domains:
        if host == domain or host.endswith("." + domain):
            return True
    return False


def _enc(s: str) -> str:
    return quote(s, safe="-_.!~*'()")


def parse_leads(raw) -> Optional[LeadsConfig]:
    if raw in (None, {}, ""):
        return None

    if not isinstance(raw, dict):
        raise ValueError("'leads' must be an object {endpoint?, email?, callback_windows?}")

    allowed_keys = {"endpoint", "email", "callback_windows"}
    unknown_keys = set(raw.keys()) - allowed_keys
    if unknown_keys:
        sorted_unknown = sorted(unknown_keys)
        raise ValueError(f"'leads' has unknown key(s): {', '.join(sorted_unknown)}")

    endpoint = raw.get("endpoint")
    email = raw.get("email")
    callback_windows = raw.get("callback_windows")

    # Validate callback_windows first
    if callback_windows is not None:
        if not isinstance(callback_windows, list):
            raise ValueError("leads.callback_windows must be a non-empty list of at most 6 distinct strings of up to 40 characters")
        if len(callback_windows) == 0:
            raise ValueError("leads.callback_windows must be a non-empty list of at most 6 distinct strings of up to 40 characters")
        if len(callback_windows) > MAX_CALLBACK_WINDOWS:
            raise ValueError("leads.callback_windows must be a non-empty list of at most 6 distinct strings of up to 40 characters")

        seen = set()
        processed = []
        for item in callback_windows:
            if not isinstance(item, str):
                raise ValueError("leads.callback_windows must be a non-empty list of at most 6 distinct strings of up to 40 characters")
            s = item.strip()
            if len(s) == 0:
                raise ValueError("leads.callback_windows must be a non-empty list of at most 6 distinct strings of up to 40 characters")
            if len(s) > MAX_WINDOW_LEN:
                raise ValueError("leads.callback_windows must be a non-empty list of at most 6 distinct strings of up to 40 characters")
            if s in seen:
                raise ValueError("leads.callback_windows must be a non-empty list of at most 6 distinct strings of up to 40 characters")
            seen.add(s)
            processed.append(s)
        callback_windows = processed
    else:
        callback_windows = list(DEFAULT_CALLBACK_WINDOWS)

    # Validate endpoint
    if endpoint is not None:
        endpoint = str(endpoint).strip()
        if not endpoint:
            endpoint = None
        else:
            parsed = urlsplit(endpoint)
            if parsed.scheme == "https":
                if not parsed.hostname:
                    raise ValueError("leads.endpoint must have a non-empty hostname")
            elif parsed.scheme == "http":
                if parsed.hostname not in ("127.0.0.1", "localhost"):
                    raise ValueError("leads.endpoint must be an https URL (http is allowed only for 127.0.0.1 or localhost)")
            else:
                raise ValueError("leads.endpoint must be an https or http URL")

            if parsed.username is not None:
                raise ValueError("leads.endpoint must not contain user:password@ credentials")

    # Validate email
    if email is not None:
        email = str(email).strip()
        if not email:
            email = None
        else:
            if not valid_email(email):
                raise ValueError("leads.email is not a valid email address")

    # At least one of endpoint or email must be set
    if endpoint is None and email is None:
        raise ValueError("'leads' needs an endpoint (https URL) or an email address to deliver requests to")

    return LeadsConfig(endpoint=endpoint, email=email, callback_windows=callback_windows)


def parse_booking(raw) -> Optional[BookingConfig]:
    if raw in (None, {}, ""):
        return None

    if not isinstance(raw, dict):
        raise ValueError("'booking' must be an object {provider, url, self_hosted?}")

    allowed_keys = {"provider", "url", "self_hosted"}
    unknown_keys = set(raw.keys()) - allowed_keys
    if unknown_keys:
        sorted_unknown = sorted(unknown_keys)
        raise ValueError(f"'booking' has unknown key(s): {', '.join(sorted_unknown)}")

    provider = raw.get("provider")
    url = raw.get("url")
    self_hosted = raw.get("self_hosted", False)

    if provider not in BOOKING_PROVIDERS:
        allowed_str = ", ".join(BOOKING_PROVIDERS)
        raise ValueError(f"booking.provider must be one of {allowed_str}")

    if not isinstance(self_hosted, bool):
        raise ValueError("booking.self_hosted must be true or false")

    if self_hosted and provider != "calcom":
        raise ValueError("booking.self_hosted is only supported for provider 'calcom'")

    if not url:
        raise ValueError("booking.url must be a non-empty string")

    url = str(url).strip()
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError("booking.url must be an https URL")

    if not parsed.hostname:
        raise ValueError("booking.url must have a non-empty hostname")

    if parsed.username is not None:
        raise ValueError("booking.url must not contain user:password@ credentials")

    # Check host
    if provider == "calcom" and self_hosted:
        pass  # Allow any host for self-hosted cal.com
    else:
        expected_hosts = PROVIDER_HOSTS[provider]
        if not _host_matches(parsed.hostname, expected_hosts):
            hint = ""
            if provider == "calcom":
                hint = " (set \"self_hosted\": true for a self-hosted cal.com instance)"
            raise ValueError(f"booking.url host '{parsed.hostname}' is not a {PROVIDER_LABELS[provider]} address{hint}")

    return BookingConfig(provider=provider, url=url, self_hosted=self_hosted)


def consent_required(country, privacy) -> bool:
    if (country or "").upper() == "DE":
        return True
    if privacy is None:
        return False
    return bool(str(privacy).strip())


def booking_prefill_url(provider: str, url: str, name: str = "", email: str = "", notes: str = "") -> str:
    parts = urlsplit(url)
    
    # Get existing query parameters
    existing = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    
    # Determine keys based on provider
    keys = {"calcom": ("name", "email", "notes"), "calendly": ("name", "email")}.get(provider)
    if keys is None:
        # Unknown provider or google - return url unchanged
        return url
    
    # Prepare values to add
    vals = {"name": name, "email": email, "notes": notes}
    added = [(k, (vals[k] or "").strip()) for k in keys if (vals[k] or "").strip()]
    
    # Build final parameter list: existing params not overridden by new ones, then new ones
    added_keys = {k for k, _ in added}
    pairs = [(k, v) for k, v in existing if k not in added_keys] + added

    # Rebuild query string
    query = "&".join(_enc(k) + "=" + _enc(v) for k, v in pairs) if pairs else ""
    
    # Reconstruct URL
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def lead_payload_fields() -> tuple[str, ...]:
    return (
        "name",
        "phone",
        "email",
        "service",
        "callback_window",
        "booking_provider",
        "message",
        "consent",
        "page_url",
        "ts"
    )
