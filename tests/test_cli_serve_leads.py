import csv
import os
import sys
from unittest.mock import patch

import pytest

from reviewforge import cli
from reviewforge.receiver import LeadStore, FIELDS


def test_serve_leads_parse():
    args = cli.build_parser().parse_args(["serve-leads", "--origin", "https://a.example"])
    assert args.host == "127.0.0.1"
    assert args.port == 8787
    assert args.db == "leads.sqlite3"
    assert args.origin == ["https://a.example"]
    assert args.func is cli._cmd_serve_leads


def test_serve_leads_missing_origin(tmp_path, capsys):
    db = tmp_path / "test.db"
    with patch("sys.argv", ["reviewforge", "serve-leads", "--db", str(db)]):
        rc = cli.main()
        assert rc == 2
        assert "--origin" in capsys.readouterr().err


def test_serve_leads_export(tmp_path, capsys):
    db = tmp_path / "test.db"
    csv_path = tmp_path / "leads.csv"

    store = LeadStore(str(db))
    store.add({
        field: "Ana R." if field == "name" else "(208) 555-0199" if field == "phone" else True if field == "consent" else ""
        for field in FIELDS
    })
    store.close()

    with patch("sys.argv", ["reviewforge", "serve-leads", "--db", str(db), "--export-csv", str(csv_path)]):
        rc = cli.main()
        assert rc == 0

    assert csv_path.exists()
    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
        assert len(rows) == 2
        assert "Ana R." in rows[1]


def test_serve_leads_serve_wiring(tmp_path, capsys):
    db = tmp_path / "test.db"

    recorded = {}

    def fake_serve(cfg, host, port):
        recorded["cfg"] = cfg
        recorded["host"] = host
        recorded["port"] = port

    with patch("sys.argv", ["reviewforge", "serve-leads", "--origin", "https://a.example", "--port", "9999", "--require-consent"]):
        with patch.object(cli.receiver_mod, "serve", fake_serve):
            with patch.object(cli.receiver_mod, "smtp_notifier_from_env", return_value=None):
                rc = cli.main()
                assert rc == 0

    assert recorded["host"] == "127.0.0.1"
    assert recorded["port"] == 9999
    assert recorded["cfg"].allowed_origins == ["https://a.example"]
    assert recorded["cfg"].require_consent is True


def test_serve_leads_non_loopback_warning(tmp_path, capsys):
    db = tmp_path / "test.db"

    def fake_serve(cfg, host, port):
        pass

    with patch("sys.argv", ["reviewforge", "serve-leads", "--origin", "https://a.example", "--host", "1.2.3.4"]):
        with patch.object(cli.receiver_mod, "serve", fake_serve):
            with patch.object(cli.receiver_mod, "smtp_notifier_from_env", return_value=None):
                rc = cli.main()
                assert rc == 0

    captured = capsys.readouterr().err
    assert "WARNING" in captured
    assert "1.2.3.4" in captured
