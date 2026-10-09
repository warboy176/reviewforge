import json
import tempfile
from pathlib import Path

import pytest

from reviewforge.sources import ManualSource

BASE = {
    "name": "Blue Line Plumbing",
    "category": "Plumber",
    "city": "Boise, ID",
    "phone": "(208) 555-0199",
    "reviews": [{"author": "A.", "rating": 5, "text": "Great work."}],
}


def test_no_leads_booking():
    data = dict(BASE)
    business = ManualSource.from_dict(data)
    assert business.leads is None
    assert business.booking is None


def test_leads_config():
    data = dict(BASE, leads={
        "endpoint": "https://leads.example/api",
        "email": "owner@bluelineplumbing.example"
    })
    business = ManualSource.from_dict(data)
    assert business.leads is not None
    assert business.leads.endpoint == "https://leads.example/api"
    assert business.leads.email == "owner@bluelineplumbing.example"
    assert business.leads.callback_windows == ["Morning", "Afternoon", "Evening"]


def test_leads_and_booking():
    data = dict(BASE, leads={
        "endpoint": "https://leads.example/api",
        "email": "owner@bluelineplumbing.example"
    }, booking={
        "provider": "calcom",
        "url": "https://cal.com/example-plumbing"
    })
    business = ManualSource.from_dict(data)
    assert business.booking is not None
    assert business.booking.provider == "calcom"


def test_booking_without_leads_raises():
    data = dict(BASE, booking={
        "provider": "calcom",
        "url": "https://cal.com/example-plumbing"
    })
    with pytest.raises(ValueError, match="'booking' needs a 'leads' block too"):
        ManualSource.from_dict(data)


def test_invalid_booking_host():
    data = dict(BASE, leads={
        "endpoint": "https://leads.example/api",
        "email": "owner@bluelineplumbing.example"
    }, booking={
        "provider": "calendly",
        "url": "https://evil.example/x"
    })
    with pytest.raises(ValueError):
        ManualSource.from_dict(data)


def test_leads_endpoint_http_raises():
    data = dict(BASE, leads={
        "endpoint": "http://leads.example/api",
        "email": "owner@bluelineplumbing.example"
    })
    with pytest.raises(ValueError):
        ManualSource.from_dict(data)


def test_load_from_json_file():
    data = dict(BASE, leads={
        "endpoint": "https://leads.example/api",
        "email": "owner@bluelineplumbing.example"
    })
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "b.json"
        with open(path, "w") as f:
            json.dump(data, f)
        business = ManualSource(str(path)).load()
        assert business.leads is not None
        assert business.leads.endpoint == "https://leads.example/api"


def test_de_business_with_leads():
    data = dict(BASE, country="DE", legal={
        "impressum": "Musterstr. 1",
        "privacy": "https://x.example/datenschutz"
    }, leads={
        "endpoint": "https://leads.example/api",
        "email": "owner@bluelineplumbing.example"
    })
    business = ManualSource.from_dict(data)
    assert business.leads is not None
