"""HTTP receiver for leads posted by ReviewForge chat widget and no-JS form.

This module binds 127.0.0.1 by default (to be exposed via a TLS reverse proxy).
It stores only what the visitor typed (no IP addresses are stored; IPs are held
in memory only for rate limiting). The business running it is the data controller.
"""
from __future__ import annotations

import csv
import html
import json
import os
import smtplib
import sqlite3
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Callable

from reviewforge.leads import BOOKING_PROVIDERS, valid_email, valid_phone


FIELDS = (
    "name",
    "phone",
    "email",
    "service",
    "callback_window",
    "booking_provider",
    "message",
    "consent",
    "page_url",
    "client_ts",
    "source"
)


@dataclass
class ReceiverConfig:
    db_path: str
    allowed_origins: list[str]            # exact origins, e.g. ["https://bluelineplumbing.example"]
    path: str = "/lead"
    max_bytes: int = 8192
    rate_limit: int = 5                   # requests per IP per window
    rate_window: float = 600.0            # seconds
    min_ms: int = 3000                    # minimum time-to-submit for the widget (elapsed_ms)
    require_consent: bool = False
    redirect_url: Optional[str] = None    # where no-JS form posts are sent after success (303)
    notify: Optional[Callable[[dict], None]] = None


class RateLimiter:
    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self._timestamps: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        if now is None:
            now = time.time()
        with self._lock:
            timestamps = self._timestamps.setdefault(key, [])
            # Drop old timestamps
            timestamps[:] = [t for t in timestamps if now - t < self.window]
            if len(timestamps) >= self.limit:
                return False
            timestamps.append(now)
            return True


class LeadStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._create_table()

    def _create_table(self):
        columns = ["id INTEGER PRIMARY KEY AUTOINCREMENT", "received_at TEXT NOT NULL"]
        for field in FIELDS:
            if field == "consent":
                columns.append(f"{field} INTEGER NOT NULL DEFAULT 0")
            else:
                columns.append(f"{field} TEXT")
        sql = f"CREATE TABLE IF NOT EXISTS leads ({', '.join(columns)})"
        self._conn.execute(sql)
        self._conn.commit()

    def add(self, lead: dict) -> int:
        with self._lock:
            received_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            values = [received_at]
            for field in FIELDS:
                value = lead.get(field, "")
                if field == "consent":
                    values.append(1 if value else 0)
                else:
                    values.append(str(value))
            placeholders = ", ".join("?" * len(values))
            sql = f"INSERT INTO leads (received_at, {', '.join(FIELDS)}) VALUES ({placeholders})"
            cursor = self._conn.execute(sql, values)
            self._conn.commit()
            return cursor.lastrowid

    def count(self) -> int:
        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*) FROM leads")
            return cursor.fetchone()[0]

    def rows(self) -> list[dict]:
        with self._lock:
            cursor = self._conn.execute(
                f"SELECT id, received_at, {', '.join(FIELDS)} FROM leads ORDER BY id"
            )
            columns = ["id", "received_at"] + list(FIELDS)
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def export_csv(self, path: str) -> int:
        rows = self.rows()
        with self._lock:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                header = ["id", "received_at"] + list(FIELDS)
                writer.writerow(header)
                for row in rows:
                    consent = "yes" if row["consent"] else "no"
                    values = [row["id"], row["received_at"]]
                    for field in FIELDS:
                        if field == "consent":
                            values.append(consent)
                        else:
                            values.append(row[field])
                    writer.writerow(values)
            return len(rows)

    def close(self):
        with self._lock:
            self._conn.close()


def origin_of(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".lower()


def is_spam(data: dict, min_ms: int) -> bool:
    if str(data.get("hp_fax") or "").strip():
        return True
    elapsed_ms = data.get("elapsed_ms")
    if elapsed_ms is not None:
        try:
            return int(elapsed_ms) < min_ms
        except ValueError:
            return True
    return False


def validate_lead(data: dict, *, require_consent=False) -> tuple[Optional[dict], Optional[str]]:
    def get(key: str, max_len: int = 0, required: bool = False):
        value = str(data.get(key) or "").strip()
        if required and not value:
            return None, f"{key} is required"
        if max_len and len(value) > max_len:
            return None, f"{key} must be at most {max_len} characters"
        return value, None

    name, err = get("name", 80, required=True)
    if err:
        return None, err

    phone, err = get("phone", required=True)
    if err:
        return None, err
    if not valid_phone(phone):
        return None, "phone is invalid"

    email, err = get("email", 254)
    if err:
        return None, err
    if email and not valid_email(email):
        return None, "email is invalid"

    service, err = get("service", 120)
    if err:
        return None, err

    callback_window, err = get("callback_window", 40)
    if err:
        return None, err

    booking_provider, err = get("booking_provider")
    if err:
        return None, err
    if booking_provider and booking_provider not in BOOKING_PROVIDERS:
        return None, f"booking_provider must be empty or one of {', '.join(BOOKING_PROVIDERS)}"

    message, err = get("message", 500)
    if err:
        return None, err

    page_url, err = get("page_url", 500)
    if err:
        return None, err
    if page_url and not (page_url.startswith("http://") or page_url.startswith("https://")):
        return None, "page_url must be empty or start with http:// or https://"

    client_ts, err = get("ts", 40)
    if err:
        return None, err

    consent_str = str(data.get("consent") or "").strip().lower()
    consent = consent_str in ("true", "yes", "on", "1")

    if require_consent and not consent:
        return None, "consent is required"

    source = "form" if data.get("form") == "nojs" else "chat"

    lead = {
        "name": name,
        "phone": phone,
        "email": email,
        "service": service,
        "callback_window": callback_window,
        "booking_provider": booking_provider,
        "message": message,
        "consent": consent,
        "page_url": page_url,
        "client_ts": client_ts,
        "source": source
    }

    return lead, None


def smtp_notifier_from_env(env=None) -> Optional[Callable[[dict], None]]:
    if env is None:
        env = os.environ
    host = env.get("REVIEWFORGE_SMTP_HOST")
    to_addr = env.get("REVIEWFORGE_SMTP_TO")
    from_addr = env.get("REVIEWFORGE_SMTP_FROM", env.get("REVIEWFORGE_SMTP_USER"))
    if not (host and to_addr and from_addr):
        return None

    port = int(env.get("REVIEWFORGE_SMTP_PORT", 587))
    user = env.get("REVIEWFORGE_SMTP_USER")
    password = env.get("REVIEWFORGE_SMTP_PASSWORD")
    starttls = env.get("REVIEWFORGE_SMTP_STARTTLS", "1") != "0"

    def notify(lead: dict):
        msg = EmailMessage()
        service = lead.get("service", "")
        subject = "New callback request"
        if service:
            subject += f": {service}"
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr

        body_lines = []
        for key, value in lead.items():
            if value and key not in ("hp_fax", "user", "password"):
                label = key.replace("_", " ").title()
                body_lines.append(f"{label}: {value}")
        msg.set_content("\n".join(body_lines))

        with smtplib.SMTP(host, port, timeout=20) as server:
            if starttls:
                server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)

    return notify


def _make_handler(cfg: ReceiverConfig, store: LeadStore, limiter: RateLimiter):
    class Handler(BaseHTTPRequestHandler):
        server_version = "reviewforge-leads"
        sys_version = ""

        def log_message(self, fmt, *args):
            # Write only command and path to stderr
            print(f"{self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}", file=sys.stderr)

        def _origin(self) -> str:
            origin = self.headers.get("Origin", "")
            if not origin:
                referer = self.headers.get("Referer", "")
                origin = origin_of(referer)
            return origin

        def _allowed(self, origin: str) -> bool:
            allowed = {o.rstrip("/").lower() for o in cfg.allowed_origins}
            return origin.rstrip("/").lower() in allowed

        def _send_json(self, status: int, obj: dict, origin: Optional[str] = None):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if origin and self._allowed(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)

        def _success(self, is_form: bool, origin: str):
            if is_form:
                redirect_url = cfg.redirect_url
                if redirect_url:
                    self.send_response(303)
                    self.send_header("Location", redirect_url)
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    html_content = f"<!doctype html><title>Request sent</title><p>Thanks, your request has been sent.</p><p><a href=\"{html.escape(origin)}/\">Back to the website</a></p>"
                    self.send_header("Content-Length", str(len(html_content.encode("utf-8"))))
                    self.end_headers()
                    self.wfile.write(html_content.encode("utf-8"))
            else:
                self._send_json(200, {"ok": True}, origin=origin)

        def do_OPTIONS(self):
            if self.path.split("?")[0] != cfg.path:
                self.send_response(404)
                self.end_headers()
                return
            origin = self._origin()
            if self._allowed(origin):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
                self.send_header("Vary", "Origin")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.send_response(403)
                self.end_headers()

        def do_GET(self):
            self._send_json(405, {"ok": False, "error": "method not allowed"})

        def do_PUT(self):
            self._send_json(405, {"ok": False, "error": "method not allowed"})

        def do_DELETE(self):
            self._send_json(405, {"ok": False, "error": "method not allowed"})

        def do_POST(self):
            path = self.path.split("?")[0]
            if path != cfg.path:
                self.send_response(404)
                self.end_headers()
                return

            origin = self._origin()
            if not self._allowed(origin):
                self._send_json(
                    403,
                    {"ok": False, "error": "origin not allowed"}
                )
                return

            client_ip = self.client_address[0]
            if not limiter.allow(client_ip):
                self.send_response(429)
                self.send_header("Retry-After", str(int(cfg.rate_window)))
                self.end_headers()
                return

            content_length = self.headers.get("Content-Length")
            if not content_length:
                self.send_response(411)
                self.end_headers()
                return
            try:
                length = int(content_length)
            except ValueError:
                self.send_response(411)
                self.end_headers()
                return
            if length > cfg.max_bytes:
                self._send_json(
                    413,
                    {"ok": False, "error": "payload too large"},
                    origin=origin
                )
                # Do not read the body
                self.close_connection = True
                return

            body = self.rfile.read(length)
            content_type = self.headers.get("Content-Type", "").split(";")[0].lower()

            if content_type == "application/json":
                try:
                    data = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError:
                    self.send_response(400)
                    self.end_headers()
                    return
                if not isinstance(data, dict):
                    self.send_response(400)
                    self.end_headers()
                    return
            elif content_type == "application/x-www-form-urlencoded":
                data = {k: v[0] for k, v in urllib.parse.parse_qs(
                    body.decode("utf-8"), keep_blank_values=True).items()}
            else:
                self.send_response(415)
                self.end_headers()
                return

            is_form = (content_type == "application/x-www-form-urlencoded") or (data.get("form") == "nojs")

            if is_spam(data, cfg.min_ms):
                # Respond as success but store nothing and do not notify
                self._success(is_form, origin)
                return

            lead, error = validate_lead(data, require_consent=cfg.require_consent)
            if error:
                self._send_json(400, {"ok": False, "error": error}, origin=origin)
                return

            lead_id = store.add(lead)
            if cfg.notify:
                try:
                    cfg.notify(lead)
                except Exception as e:
                    print(f"notify failed: {type(e).__name__}", file=sys.stderr)

            self._success(is_form, origin)

    return Handler


def build_server(cfg: ReceiverConfig, host="127.0.0.1", port=8787) -> ThreadingHTTPServer:
    store = LeadStore(cfg.db_path)
    limiter = RateLimiter(cfg.rate_limit, cfg.rate_window)
    handler = _make_handler(cfg, store, limiter)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    server.store = store
    return server


def serve(cfg: ReceiverConfig, host="127.0.0.1", port=8787) -> None:
    server = build_server(cfg, host, port)
    print(f"Listening on http://{host}:{server.server_address[1]}{cfg.path} (origins: {', '.join(cfg.allowed_origins)})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.store.close()
