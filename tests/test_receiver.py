import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from http.client import HTTPResponse
from pathlib import Path
from unittest.mock import patch

import pytest
from reviewforge.receiver import (
    ReceiverConfig,
    build_server,
    is_spam,
    validate_lead,
    RateLimiter,
    LeadStore,
    smtp_notifier_from_env,
)


def make_server(**overrides):
    """Create a test server with ephemeral port."""
    import tempfile
    default_db = overrides.pop("db_path", None)
    if default_db is None:
        fd, default_db = tempfile.mkstemp(suffix=".sqlite3"); os.close(fd)
    cfg = ReceiverConfig(
        db_path=str(default_db),
        allowed_origins=["https://bluelineplumbing.example"],
        rate_limit=3,
        rate_window=60,
        max_bytes=2048,
        **overrides
    )
    srv = build_server(cfg, "127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{srv.server_address[1]}"
    url = base_url + cfg.path
    return (srv, cfg, url)


@pytest.fixture
def server(tmp_path):
    """Create a test server with ephemeral port."""
    srv, cfg, url = make_server(db_path=tmp_path / "leads.sqlite3")
    yield (srv, cfg, url)
    srv.shutdown()
    srv.server_close()
    srv.store.close()


def post(url, body: bytes, headers: dict):
    """Helper to make POST requests."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            status = response.getcode()
            headers = dict(response.headers)
            body = response.read()
    except urllib.error.HTTPError as e:
        status = e.code
        headers = dict(e.headers)
        body = e.read()
    return (status, headers, body)


VALID = {
    "name": "Ana R.",
    "phone": "(208) 555-0199",
    "email": "ana@example.com",
    "service": "Drain cleaning",
    "callback_window": "Morning",
    "booking_provider": "",
    "message": "",
    "consent": True,
    "page_url": "https://bluelineplumbing.example/",
    "ts": "2026-10-08T10:00:00Z",
    "hp_fax": "",
    "elapsed_ms": 9000
}


def test_valid_json_post(server):
    srv, cfg, url = server
    body = json.dumps(VALID).encode("utf-8")
    headers = {"Origin": "https://bluelineplumbing.example", "Content-Type": "application/json"}
    status, headers, _ = post(url, body, headers)
    assert status == 200
    assert headers["Access-Control-Allow-Origin"] == "https://bluelineplumbing.example"
    assert srv.store.count() == 1
    rows = srv.store.rows()
    assert rows[0]["name"] == "Ana R."
    assert rows[0]["consent"] == 1
    # R2: Check that name is in the right column, not shifted into 'name'
    assert rows[0]["received_at"].endswith("Z")


def test_honeypot(server):
    srv, cfg, url = server
    data = VALID.copy()
    data["hp_fax"] = "123"
    body = json.dumps(data).encode("utf-8")
    headers = {"Origin": "https://bluelineplumbing.example", "Content-Type": "application/json"}
    status, _, _ = post(url, body, headers)
    assert status == 200
    assert srv.store.count() == 0


def test_too_fast(server):
    srv, cfg, url = server
    data = VALID.copy()
    data["elapsed_ms"] = 500
    body = json.dumps(data).encode("utf-8")
    headers = {"Origin": "https://bluelineplumbing.example", "Content-Type": "application/json"}
    status, _, _ = post(url, body, headers)
    assert status == 200
    assert srv.store.count() == 0


def test_invalid_phone(server):
    srv, cfg, url = server
    data = VALID.copy()
    data["phone"] = "invalid"
    body = json.dumps(data).encode("utf-8")
    headers = {"Origin": "https://bluelineplumbing.example", "Content-Type": "application/json"}
    status, _, _ = post(url, body, headers)
    assert status == 400
    assert srv.store.count() == 0


def test_disallowed_origin(server):
    srv, cfg, url = server
    body = json.dumps(VALID).encode("utf-8")
    headers = {"Origin": "https://evil.example", "Content-Type": "application/json"}
    status, headers, _ = post(url, body, headers)
    assert status == 403
    assert "Access-Control-Allow-Origin" not in headers
    assert srv.store.count() == 0


def test_options_preflight(server):
    srv, cfg, url = server
    req = urllib.request.Request(url, method="OPTIONS")
    req.add_header("Origin", "https://bluelineplumbing.example")
    try:
        with urllib.request.urlopen(req) as response:
            status = response.getcode()
            headers = dict(response.headers)
    except urllib.error.HTTPError as e:
        status = e.code
        headers = dict(e.headers)
    assert status == 204
    assert "Access-Control-Allow-Methods" in headers
    assert "POST" in headers["Access-Control-Allow-Methods"]

    req = urllib.request.Request(url, method="OPTIONS")
    req.add_header("Origin", "https://evil.example")
    try:
        with urllib.request.urlopen(req) as response:
            status = response.getcode()
            headers = dict(response.headers)
    except urllib.error.HTTPError as e:
        status = e.code
        headers = dict(e.headers)
    assert status == 403


def test_size_cap(server):
    srv, cfg, url = server
    data = VALID.copy()
    data["message"] = "x" * 3000
    body = json.dumps(data).encode("utf-8")
    headers = {"Origin": "https://bluelineplumbing.example", "Content-Type": "application/json"}
    status, _, _ = post(url, body, headers)
    assert status == 413
    assert srv.store.count() == 0


def test_rate_limit(server):
    srv, cfg, url = server
    for i in range(3):
        body = json.dumps(VALID).encode("utf-8")
        headers = {"Origin": "https://bluelineplumbing.example", "Content-Type": "application/json"}
        status, _, _ = post(url, body, headers)
        assert status == 200
    body = json.dumps(VALID).encode("utf-8")
    headers = {"Origin": "https://bluelineplumbing.example", "Content-Type": "application/json"}
    status, headers, _ = post(url, body, headers)
    assert status == 429
    assert "Retry-After" in headers


def test_wrong_path(server):
    srv, cfg, url = server
    # Build the wrong path using base URL and cfg.path
    base = url[: -len(cfg.path)]
    wrong = base + "/other"
    # POST to wrong path should return 404
    req = urllib.request.Request(wrong, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            status = response.getcode()
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 404

    # GET to correct path should return 405
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req) as response:
            status = response.getcode()
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 405


def test_nojs_form_post(server):
    srv, cfg, url = server
    data = {k: str(v) for k, v in VALID.items()}
    data["consent"] = "yes"
    data["form"] = "nojs"
    body = urllib.parse.urlencode(data).encode("utf-8")
    headers = {"Origin": "https://bluelineplumbing.example", "Content-Type": "application/x-www-form-urlencoded"}
    status, _, _ = post(url, body, headers)
    assert status == 200
    assert srv.store.count() == 1
    rows = srv.store.rows()
    assert rows[0]["source"] == "form"
    assert rows[0]["consent"] == 1


def test_form_post_with_redirect():
    srv, cfg, url = make_server(redirect_url="https://bluelineplumbing.example/#lead-sent")
    try:
        data = {k: str(v) for k, v in VALID.items()}
        data["consent"] = "yes"
        data["form"] = "nojs"
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers = {"Origin": "https://bluelineplumbing.example", "Content-Type": "application/x-www-form-urlencoded"}

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        try:
            resp = opener.open(urllib.request.Request(url, data=body, headers=headers, method="POST"))
            status, loc = resp.getcode(), resp.headers.get("Location")
        except urllib.error.HTTPError as e:
            status, loc = e.code, e.headers.get("Location")
        assert status == 303
        assert loc == "https://bluelineplumbing.example/#lead-sent"
    finally:
        srv.shutdown()
        srv.server_close()
        srv.store.close()


def test_require_consent_false():
    srv, cfg, url = make_server(require_consent=True)
    try:
        data = VALID.copy()
        data["consent"] = False
        body = json.dumps(data).encode("utf-8")
        headers = {"Origin": "https://bluelineplumbing.example", "Content-Type": "application/json"}
        status, _, _ = post(url, body, headers)
        assert status == 400
    finally:
        srv.shutdown()
        srv.server_close()
        srv.store.close()


def test_validate_lead_unit_tests():
    # booking_provider "zoom" -> error
    lead, err = validate_lead({"booking_provider": "zoom"})
    assert err is not None

    # page_url "javascript:alert(1)" -> error
    lead, err = validate_lead({"page_url": "javascript:alert(1)"})
    assert err is not None

    # name of 81 chars -> error
    lead, err = validate_lead({"name": "x" * 81})
    assert err is not None


def test_is_spam_unit_tests():
    assert is_spam({"hp_fax": "x"}, 3000) == True
    assert is_spam({"elapsed_ms": "abc"}, 3000) == True
    assert is_spam({"elapsed_ms": 5000}, 3000) == False
    assert is_spam({}, 3000) == False


def test_leadstore_export_csv(server, tmp_path):
    srv, cfg, url = server
    body = json.dumps(VALID).encode("utf-8")
    headers = {"Origin": "https://bluelineplumbing.example", "Content-Type": "application/json"}
    post(url, body, headers)
    path = tmp_path / "leads.csv"
    count = srv.store.export_csv(str(path))
    assert count == 1
    with open(path, "r") as f:
        content = f.read()
        assert content.startswith("id,received_at,name,phone")


def test_rate_limiter_unit_test():
    limiter = RateLimiter(2, 10)
    assert limiter.allow("key", 0) == True
    assert limiter.allow("key", 1) == True
    assert limiter.allow("key", 2) == False
    assert limiter.allow("key", 11.5) == True


def test_smtp_notifier_from_env():
    # Empty env -> None
    assert smtp_notifier_from_env({}) is None

    # With required fields set -> callable
    with patch.dict(os.environ, {
        "REVIEWFORGE_SMTP_HOST": "smtp.example.com",
        "REVIEWFORGE_SMTP_TO": "to@example.com",
        "REVIEWFORGE_SMTP_FROM": "from@example.com"
    }):
        notifier = smtp_notifier_from_env()
        assert notifier is not None
        # Do not call it, just ensure it's a callable
        assert callable(notifier)

    # R6: Test that FROM defaults to REVIEWFORGE_SMTP_USER if not set
    with patch.dict(os.environ, {
        "REVIEWFORGE_SMTP_HOST": "h",
        "REVIEWFORGE_SMTP_TO": "t@x.example",
        "USER": "someone"
    }):
        assert smtp_notifier_from_env({}) is None
