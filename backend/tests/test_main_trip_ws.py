"""End-to-end WS save → list → load round-trip with TestClient."""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _reload_with_env(**env: str):
    for k in ("APP_ENV", "REQUIRE_CLERK_AUTH", "DEMO_ACCESS_TOKEN",
              "CLERK_JWT_ISSUER", "CLERK_JWKS_URL", "TEST_DATABASE_URL"):
        os.environ.pop(k, None)
    os.environ.update(env)
    for mod in ("auth", "db", "models", "repository", "main"):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
        else:
            importlib.import_module(mod)
    # Make sure tables exist in the freshly-rebound DB.
    from db import get_engine
    from models import Base
    Base.metadata.create_all(get_engine())
    return sys.modules["main"]


class WsSaveLoadTests(unittest.TestCase):
    def setUp(self):
        # Per-test isolated SQLite file.
        self._tmp = tempfile.NamedTemporaryFile(
            prefix="_test_ws_", suffix=".sqlite3", delete=False, dir=str(BACKEND_DIR)
        )
        self._tmp.close()
        self.url = f"sqlite:///{self._tmp.name}"
        self.main = _reload_with_env(APP_ENV="test", TEST_DATABASE_URL=self.url)

    def tearDown(self):
        try:
            os.remove(self._tmp.name)
        except OSError:
            pass

    def _open_ws(self, client):
        return client.websocket_connect("/ws")

    def test_save_list_load_roundtrip(self):
        from fastapi.testclient import TestClient
        with TestClient(self.main.app) as client, self._open_ws(client) as ws:
            ws.send_json({
                "type": "save_trip",
                "data": {
                    "gp_slug": "italian-gp-2026",
                    "depart_date": "2026-09-04",
                    "return_date": "2026-09-08",
                    "plan_snapshot": {"results": [{"id": 1}]},
                    "budget_summary": {"total": 1234, "currency": "EUR"},
                    "active_constraints": {"direct_only": True},
                },
            })
            ack = ws.receive_json()
            self.assertEqual(ack["type"], "save_trip_ack")
            self.assertIn("id", ack["data"])
            trip_id = ack["data"]["id"]

            ws.send_json({"type": "list_trips", "data": {}})
            lst = ws.receive_json()
            self.assertEqual(lst["type"], "trips_list")
            self.assertEqual(len(lst["data"]["trips"]), 1)
            self.assertEqual(lst["data"]["trips"][0]["gp_slug"], "italian-gp-2026")
            self.assertEqual(lst["data"]["trips"][0]["budget_total"], 1234)

            ws.send_json({"type": "load_trip", "data": {"id": trip_id}})
            loaded = ws.receive_json()
            self.assertEqual(loaded["type"], "trip_loaded")
            self.assertEqual(loaded["data"]["plan_snapshot"], {"results": [{"id": 1}]})
            self.assertEqual(loaded["data"]["active_constraints"], {"direct_only": True})

    def test_save_without_plan_returns_error(self):
        from fastapi.testclient import TestClient
        with TestClient(self.main.app) as client, self._open_ws(client) as ws:
            ws.send_json({
                "type": "save_trip",
                "data": {"gp_slug": "x"},  # no plan_snapshot, no plan_state on session
            })
            err = ws.receive_json()
            self.assertEqual(err["type"], "error")

    def test_load_unknown_id_returns_error(self):
        from fastapi.testclient import TestClient
        with TestClient(self.main.app) as client, self._open_ws(client) as ws:
            ws.send_json({"type": "load_trip", "data": {"id": "not-a-uuid"}})
            err = ws.receive_json()
            self.assertEqual(err["type"], "error")

    def test_delete_trip_returns_ack(self):
        from fastapi.testclient import TestClient
        with TestClient(self.main.app) as client, self._open_ws(client) as ws:
            ws.send_json({
                "type": "save_trip",
                "data": {
                    "gp_slug": "x",
                    "plan_snapshot": {"k": 1},
                },
            })
            ack = ws.receive_json()
            trip_id = ack["data"]["id"]
            ws.send_json({"type": "delete_trip", "data": {"id": trip_id}})
            del_ack = ws.receive_json()
            self.assertEqual(del_ack["type"], "delete_trip_ack")
            self.assertTrue(del_ack["data"]["ok"])

            # Second delete returns ok=False (idempotent).
            ws.send_json({"type": "delete_trip", "data": {"id": trip_id}})
            del_ack2 = ws.receive_json()
            self.assertEqual(del_ack2["type"], "delete_trip_ack")
            self.assertFalse(del_ack2["data"]["ok"])


if __name__ == "__main__":
    unittest.main()
