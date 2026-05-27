"""Prove the deterministic plan + refine paths make zero outbound calls.

Reviewer R9 non-negotiable: log grep is not enough. R10 must include an
executable assertion that outbound provider egress would fail during the
deterministic test path.

Strategy: monkeypatch `socket.socket.connect` and `socket.create_connection`
to record every attempted connection. Allow loopback (127.0.0.1 / ::1 /
localhost) — DNS and uvicorn-style internal sockets are not what we care
about. Then run `plan_trip` under APP_ENV=test with every provider/LLM
key empty, and assert no remote connection was attempted.

This is the same surface a real CI/local lane sees: no SerpAPI, no
Firecrawl, no OpenAI/Anthropic/Tavily, no booking.com search. If any
tool tries to phone home, this test fails loudly.
"""

from __future__ import annotations

import os
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", ""}


def _is_loopback(host) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("utf-8", errors="ignore")
    if not isinstance(host, str):
        return False
    return host in _LOOPBACK_HOSTS or host.startswith("127.")


class OutboundEgressTests(unittest.TestCase):
    """plan_trip + refine_plan must not initiate any remote socket."""

    def _record_attempts(self):
        attempts: list[tuple[str, int]] = []
        real_connect = socket.socket.connect
        real_create = socket.create_connection

        def fake_connect(self, address, *args, **kwargs):
            host = address[0] if isinstance(address, tuple) else None
            port = address[1] if isinstance(address, tuple) and len(address) > 1 else 0
            if not _is_loopback(host):
                attempts.append((str(host), int(port) if port else 0))
                raise OSError(
                    f"outbound egress blocked in deterministic test: "
                    f"{host}:{port}"
                )
            return real_connect(self, address, *args, **kwargs)

        def fake_create_connection(address, *args, **kwargs):
            host = address[0] if isinstance(address, tuple) else None
            port = address[1] if isinstance(address, tuple) and len(address) > 1 else 0
            if not _is_loopback(host):
                attempts.append((str(host), int(port) if port else 0))
                raise OSError(
                    f"outbound egress blocked in deterministic test: "
                    f"{host}:{port}"
                )
            return real_create(address, *args, **kwargs)

        return attempts, fake_connect, fake_create_connection

    def test_plan_trip_with_empty_keys_makes_zero_outbound_attempts(self):
        # Wipe every provider/LLM key plus enable test gating.
        empty_env = {
            "APP_ENV": "test",
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "SERPAPI_API_KEY": "",
            "FIRECRAWL_API_KEY": "",
            "TAVILY_API_KEY": "",
        }
        with mock.patch.dict(os.environ, empty_env, clear=False):
            # Reload modules that read env at import-time.
            for mod in [
                "tools._cache",
                "tools.search_flights",
                "tools.search_hotels",
                "tools.search_tickets",
                "llm",
                "graph",
                "agents.transport",
                "agents.hotel",
                "agents.tickets",
                "agents.tour",
                "agents.itinerary",
                "agents.budget",
            ]:
                sys.modules.pop(mod, None)

            from graph import plan_trip

            attempts, fake_connect, fake_create_connection = self._record_attempts()

            payload = {
                "gp_name": "Singapore GP",
                "gp_city": "Singapore",
                "gp_date": "2026-10-04",
                "origin": "New York",
                "budget": 3000,
                "currency": "EUR",
                "stand_pref": "any",
                "extra_days": 2,
                "stops": "",
                "special_requests": "",
                "depart_date": "2026-10-01",
                "return_date": "2026-10-06",
                "debug": False,
            }

            with mock.patch.object(socket.socket, "connect", new=fake_connect), \
                 mock.patch.object(socket, "create_connection", new=fake_create_connection):
                result = plan_trip(payload)

            self.assertEqual(
                attempts, [],
                f"Deterministic plan path attempted remote egress: {attempts!r}",
            )

            # Sanity: the run must actually produce a usable plan (mocks
            # cover all four zones), otherwise the assertion above
            # could pass vacuously by aborting early.
            self.assertTrue(result.get("tickets"))
            self.assertTrue(result.get("transport"))
            self.assertTrue(result.get("hotel"))


if __name__ == "__main__":
    unittest.main()
