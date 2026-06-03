"""Hardening tests: Sentry before_send scrubs WS-handshake credentials (security-6).

The WS handshake carries the Clerk JWT / demo token in the query string
(?token=, ?demo_token=). _scrub_event / _scrub_url_query strip those values
before any event leaves the process, so a captured handshake URL cannot leak
live credentials into the error tracker. Pure-function tests; no Sentry SDK or
network is required.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import observability as obs  # noqa: E402


class ScrubUrlQueryTests(unittest.TestCase):
    def test_token_value_filtered(self):
        out = obs._scrub_url_query("wss://api.example/ws?token=eyJhbGciOi.secret")
        self.assertNotIn("eyJhbGciOi.secret", out)
        self.assertIn("token=%5BFiltered%5D", out)  # urlencoded [Filtered]

    def test_demo_token_filtered(self):
        out = obs._scrub_url_query("wss://api.example/ws?demo_token=topsecret")
        self.assertNotIn("topsecret", out)

    def test_non_sensitive_params_preserved(self):
        out = obs._scrub_url_query("https://api.example/x?gp=monza&token=abc")
        self.assertIn("gp=monza", out)
        self.assertNotIn("abc", out)

    def test_url_without_query_unchanged(self):
        url = "https://api.example/healthz"
        self.assertEqual(obs._scrub_url_query(url), url)

    def test_empty_url_safe(self):
        self.assertEqual(obs._scrub_url_query(""), "")


class ScrubEventTests(unittest.TestCase):
    def test_request_url_scrubbed(self):
        event = {"request": {"url": "wss://api.example/ws?token=LEAK"}}
        out = obs._scrub_event(event, None)
        self.assertNotIn("LEAK", out["request"]["url"])

    def test_request_query_string_scrubbed(self):
        event = {"request": {"query_string": "token=LEAK&gp=spa"}}
        out = obs._scrub_event(event, None)
        self.assertNotIn("LEAK", out["request"]["query_string"])
        self.assertIn("gp=spa", out["request"]["query_string"])

    def test_breadcrumb_url_scrubbed(self):
        event = {
            "breadcrumbs": {
                "values": [{"data": {"url": "wss://api.example/ws?demo_token=LEAK"}}]
            }
        }
        out = obs._scrub_event(event, None)
        self.assertNotIn("LEAK", out["breadcrumbs"]["values"][0]["data"]["url"])

    def test_event_without_request_is_passthrough(self):
        event = {"level": "error", "message": "boom"}
        self.assertEqual(obs._scrub_event(event, None), event)

    def test_malformed_event_does_not_raise(self):
        # Scrubbing must never drop an event by raising.
        self.assertEqual(obs._scrub_event(None, None), None)


if __name__ == "__main__":
    unittest.main()
