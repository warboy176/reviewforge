import pytest
from reviewforge.leads import (
    parse_leads, parse_booking, consent_required, booking_prefill_url,
    valid_phone, valid_email, lead_payload_fields, LeadsConfig, BookingConfig
)
import re

def test_parse_leads_none_empty():
    assert parse_leads(None) is None
    assert parse_leads({}) is None
    assert parse_leads("") is None

def test_parse_leads_valid_full():
    result = parse_leads({
        "endpoint": "https://example.com/lead",
        "email": "test@example.com"
    })
    assert result.endpoint == "https://example.com/lead"
    assert result.email == "test@example.com"
    assert result.callback_windows == list(("Morning", "Afternoon", "Evening"))

def test_parse_leads_endpoint_http_rejected():
    with pytest.raises(ValueError, match=re.escape("leads.endpoint must be an https URL (http is allowed only for 127.0.0.1 or localhost)")):
        parse_leads({"endpoint": "http://evil.example"})

def test_parse_leads_endpoint_local_accepted():
    result = parse_leads({"endpoint": "http://127.0.0.1:8787/lead"})
    assert result.endpoint == "http://127.0.0.1:8787/lead"

def test_parse_leads_endpoint_creds_rejected():
    with pytest.raises(ValueError, match=re.escape("leads.endpoint must not contain user:password@ credentials")):
        parse_leads({"endpoint": "https://user:pw@x.example"})

def test_parse_leads_bad_email_rejected():
    with pytest.raises(ValueError, match=re.escape("leads.email is not a valid email address")):
        parse_leads({"email": "bad-email"})

def test_parse_leads_neither_endpoint_nor_email_rejected():
    with pytest.raises(ValueError, match=re.escape("'leads' needs an endpoint (https URL) or an email address to deliver requests to")):
        parse_leads({"email": "   "})

def test_parse_leads_unknown_key_rejected():
    with pytest.raises(ValueError, match=re.escape("'leads' has unknown key(s): unknown")):
        parse_leads({"endpoint": "https://example.com", "unknown": "key"})

def test_parse_leads_callback_windows_empty_list_rejected():
    with pytest.raises(ValueError, match=re.escape("leads.callback_windows must be a non-empty list of at most 6 distinct strings of up to 40 characters")):
        parse_leads({"endpoint": "https://leads.example/lead", "callback_windows": []})

def test_parse_leads_callback_windows_too_many_items_rejected():
    with pytest.raises(ValueError, match=re.escape("leads.callback_windows must be a non-empty list of at most 6 distinct strings of up to 40 characters")):
        parse_leads({"endpoint": "https://leads.example/lead", "callback_windows": ["A"] * 7})

def test_parse_leads_callback_windows_duplicate_rejected():
    with pytest.raises(ValueError, match=re.escape("leads.callback_windows must be a non-empty list of at most 6 distinct strings of up to 40 characters")):
        parse_leads({"endpoint": "https://leads.example/lead", "callback_windows": ["A", "A"]})

def test_parse_leads_callback_windows_non_string_rejected():
    with pytest.raises(ValueError, match=re.escape("leads.callback_windows must be a non-empty list of at most 6 distinct strings of up to 40 characters")):
        parse_leads({"endpoint": "https://leads.example/lead", "callback_windows": [123]})

def test_parse_leads_callback_windows_too_long_rejected():
    with pytest.raises(ValueError, match=re.escape("leads.callback_windows must be a non-empty list of at most 6 distinct strings of up to 40 characters")):
        parse_leads({"endpoint": "https://leads.example/lead", "callback_windows": ["A" * 41]})

def test_parse_leads_callback_windows_custom_kept():
    result = parse_leads({"endpoint": "https://leads.example/lead", "callback_windows": ["Morning", "Evening"]})
    assert result.callback_windows == ["Morning", "Evening"]

def test_parse_booking_none_empty():
    assert parse_booking(None) is None
    assert parse_booking({}) is None
    assert parse_booking("") is None

def test_parse_booking_calcom_ok():
    result = parse_booking({
        "provider": "calcom",
        "url": "https://cal.com/example-plumbing"
    })
    assert result.provider == "calcom"
    assert result.url == "https://cal.com/example-plumbing"
    assert result.self_hosted is False

def test_parse_booking_calcom_subdomain_ok():
    result = parse_booking({
        "provider": "calcom",
        "url": "https://app.cal.com/x"
    })
    assert result.provider == "calcom"
    assert result.url == "https://app.cal.com/x"

def test_parse_booking_calcom_http_rejected():
    with pytest.raises(ValueError, match=re.escape("booking.url must be an https URL")):
        parse_booking({
            "provider": "calcom",
            "url": "http://cal.com/x"
        })

def test_parse_booking_calcom_bad_host_rejected():
    with pytest.raises(ValueError, match=re.escape("booking.url host 'cal.com.evil.example' is not a cal.com address")):
        parse_booking({
            "provider": "calcom",
            "url": "https://cal.com.evil.example/x"
        })

def test_parse_booking_calcom_self_hosted_false_rejected():
    with pytest.raises(ValueError, match=re.escape("booking.url host 'book.example-plumbing.example' is not a cal.com address")):
        parse_booking({
            "provider": "calcom",
            "url": "https://book.example-plumbing.example/x"
        })

def test_parse_booking_calcom_self_hosted_true_accepted():
    result = parse_booking({
        "provider": "calcom",
        "url": "https://book.example-plumbing.example/x",
        "self_hosted": True
    })
    assert result.self_hosted is True

def test_parse_booking_self_hosted_non_calcom_rejected():
    with pytest.raises(ValueError, match=re.escape("booking.self_hosted is only supported for provider 'calcom'")):
        parse_booking({
            "provider": "calendly",
            "url": "https://calendly.com/example",
            "self_hosted": True
        })

def test_parse_booking_self_hosted_non_bool_rejected():
    with pytest.raises(ValueError, match=re.escape("booking.self_hosted must be true or false")):
        parse_booking({
            "provider": "calcom",
            "url": "https://cal.com/x",
            "self_hosted": "yes"
        })

def test_parse_booking_calendly_ok():
    result = parse_booking({
        "provider": "calendly",
        "url": "https://calendly.com/example"
    })
    assert result.provider == "calendly"
    assert result.url == "https://calendly.com/example"

def test_parse_booking_google_ok():
    result = parse_booking({
        "provider": "google",
        "url": "https://calendar.app.google/abc123"
    })
    assert result.provider == "google"
    assert result.url == "https://calendar.app.google/abc123"

    result = parse_booking({
        "provider": "google",
        "url": "https://calendar.google.com/calendar/appointments/schedules/abc"
    })
    assert result.provider == "google"
    assert result.url == "https://calendar.google.com/calendar/appointments/schedules/abc"

def test_parse_booking_google_bad_host_rejected():
    with pytest.raises(ValueError, match=re.escape("booking.url host 'evil.example' is not a Google Calendar (calendar.app.google / calendar.google.com) address")):
        parse_booking({
            "provider": "google",
            "url": "https://evil.example/x"
        })

def test_parse_booking_unknown_provider_rejected():
    with pytest.raises(ValueError, match=re.escape("booking.provider must be one of calcom, google, calendly")):
        parse_booking({
            "provider": "unknown",
            "url": "https://example.com"
        })

def test_parse_booking_unknown_key_rejected():
    with pytest.raises(ValueError, match=re.escape("'booking' has unknown key(s): unknown")):
        parse_booking({
            "provider": "calcom",
            "url": "https://cal.com/x",
            "unknown": "key"
        })


def test_consent_required_de():
    assert consent_required("DE", None) is True

def test_consent_required_de_lower():
    assert consent_required("de", "") is True

def test_consent_required_privacy():
    assert consent_required("US", "https://x.example/privacy") is True

def test_consent_required_none():
    assert consent_required("US", None) is False

def test_consent_required_empty_privacy():
    assert consent_required(None, "  ") is False

def test_booking_prefill_url_calcom():
    result = booking_prefill_url(
        "calcom",
        "https://cal.com/example-plumbing",
        name="Ana R",
        email="ana@example.com",
        notes="Leak & drip"
    )
    assert result == "https://cal.com/example-plumbing?name=Ana%20R&email=ana%40example.com&notes=Leak%20%26%20drip"

def test_booking_prefill_url_calendly():
    result = booking_prefill_url(
        "calendly",
        "https://calendly.com/example",
        name="Ana R",
        email="ana@example.com",
        notes="Leak & drip"
    )
    assert result == "https://calendly.com/example?name=Ana%20R&email=ana%40example.com"

def test_booking_prefill_url_google():
    result = booking_prefill_url(
        "google",
        "https://calendar.app.google/abc123",
        name="Ana R",
        email="ana@example.com"
    )
    assert result == "https://calendar.app.google/abc123"

def test_booking_prefill_url_empty_values_omitted():
    result = booking_prefill_url(
        "calcom",
        "https://cal.com/example-plumbing",
        name="Ana R"
    )
    assert result == "https://cal.com/example-plumbing?name=Ana%20R"

def test_booking_prefill_url_existing_params_preserved():
    result = booking_prefill_url(
        "calcom",
        "https://cal.com/x?month=2026-10&name=old",
        name="New"
    )
    assert result == "https://cal.com/x?month=2026-10&name=New"

def test_booking_prefill_url_fragment_preserved():
    result = booking_prefill_url(
        "calcom",
        "https://cal.com/example-plumbing#section1",
        name="Ana R"
    )
    assert result == "https://cal.com/example-plumbing?name=Ana%20R#section1"

def test_valid_phone_examples():
    assert valid_phone("(208) 555-0199") is True
    assert valid_phone("+49 30 1234567") is True
    assert valid_phone("12345") is False
    assert valid_phone("555-abc-1234") is False
    assert valid_phone("++4930123456") is False

def test_valid_email_examples():
    assert valid_email("test@example.com") is True
    assert valid_email("user.name@domain.co.uk") is True
    assert valid_email("bad-email") is False
    assert valid_email("") is False
    assert valid_email(None) is False

def test_lead_payload_fields():
    fields = lead_payload_fields()
    assert len(fields) == 10
    assert "consent" in fields
    assert "page_url" in fields
    assert "ts" in fields


def test_booking_prefill_url_replaced_param_moves_to_end():
    assert booking_prefill_url("calcom", "https://cal.com/x?name=old&month=2026-10", name="New") == "https://cal.com/x?month=2026-10&name=New"
