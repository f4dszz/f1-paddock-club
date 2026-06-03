"""test-coverage-10: multi-tenant persistence isolation (_persistence_blocked).

On a real (non-local) deploy the shared "demo-user" sentinel must NOT own
persisted trips — otherwise every anonymous demo visitor collapses into one
account and can read/delete each other's saved trips. Local/test dev runs as
demo-user legitimately (single developer), so persistence stays open there.

The guard `_persistence_blocked(user_id) == (user_id == "demo-user" and not
_IS_LOCAL_ENV)` is the security control. Every WS persistence handler
(save/list/load/delete) calls it first. Before this file the TRUE branch — the
actual data-leak protection — had zero coverage: all WS persistence tests run
under APP_ENV=test (local), where the guard always returns False.

Approach: drive the real async handlers with a DummyWS, toggling
main._IS_LOCAL_ENV. Under non-local + demo-user every handler must refuse with a
"Sign in" error and must NEVER reach the DB worker. A real (non-demo) clerk user
is allowed past the gate (DB workers patched so no real DB is touched).
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import main  # noqa: E402


class DummyWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    def types(self) -> list[str]:
        return [m.get("type") for m in self.sent]

    def first_of(self, type_name: str) -> dict | None:
        for m in self.sent:
            if m.get("type") == type_name:
                return m
        return None


def _session(user_id: str) -> dict:
    s = main.create_session()
    s["user_id"] = user_id
    return s


class PersistenceBlockedPredicateTests(unittest.TestCase):
    """Direct truth-table for the guard itself."""

    def test_demo_user_blocked_on_non_local(self):
        with patch.object(main, "_IS_LOCAL_ENV", False):
            self.assertTrue(main._persistence_blocked("demo-user"))

    def test_demo_user_allowed_on_local(self):
        with patch.object(main, "_IS_LOCAL_ENV", True):
            self.assertFalse(main._persistence_blocked("demo-user"))

    def test_real_user_never_blocked_local_or_remote(self):
        with patch.object(main, "_IS_LOCAL_ENV", False):
            self.assertFalse(main._persistence_blocked("clerk_user_abc123"))
        with patch.object(main, "_IS_LOCAL_ENV", True):
            self.assertFalse(main._persistence_blocked("clerk_user_abc123"))

    def test_session_user_id_defaults_to_demo_sentinel(self):
        self.assertEqual(main._session_user_id({}), "demo-user")
        self.assertEqual(main._session_user_id({"user_id": ""}), "demo-user")
        self.assertEqual(main._session_user_id({"user_id": "u1"}), "u1")


class DemoUserBlockedOnNonLocalTests(unittest.TestCase):
    """Every persistence handler must refuse demo-user on a real deploy and
    must NOT touch the DB worker (the multi-tenant data-leak protection)."""

    def _assert_blocked(self, coro_factory):
        ws = DummyWS()
        session = _session("demo-user")
        # Spy on every *_sync worker so we can assert NONE of them run.
        with patch.object(main, "_IS_LOCAL_ENV", False), \
             patch.object(main, "_save_trip_sync") as save_sync, \
             patch.object(main, "_list_trips_sync") as list_sync, \
             patch.object(main, "_load_trip_sync") as load_sync, \
             patch.object(main, "_delete_trip_sync") as delete_sync:
            asyncio.run(coro_factory(ws, session))
            save_sync.assert_not_called()
            list_sync.assert_not_called()
            load_sync.assert_not_called()
            delete_sync.assert_not_called()
        err = ws.first_of("error")
        self.assertIsNotNone(err, f"expected an error envelope, got {ws.types()}")
        self.assertIn("Sign in", err["data"])
        return ws

    def test_save_blocked(self):
        self._assert_blocked(
            lambda ws, s: main._handle_save_trip(
                ws, {"plan_snapshot": {"x": 1}, "gp_slug": "monza"}, s
            )
        )

    def test_list_blocked(self):
        self._assert_blocked(lambda ws, s: main._handle_list_trips(ws, s))

    def test_load_blocked(self):
        ws = self._assert_blocked(
            lambda ws, s: main._handle_load_trip(
                ws, {"id": "11111111-1111-1111-1111-111111111111"}, s
            )
        )
        # Blocked BEFORE id-parsing, so no "invalid trip id" leakage either.
        self.assertNotIn("trip_loaded", ws.types())

    def test_delete_blocked(self):
        self._assert_blocked(
            lambda ws, s: main._handle_delete_trip(
                ws, {"id": "11111111-1111-1111-1111-111111111111"}, s
            )
        )


class RealUserAllowedTests(unittest.TestCase):
    """A real (non-demo) clerk user passes the gate even on a non-local deploy,
    and the handler scopes the DB call to THAT user id."""

    def test_real_user_save_passes_gate_and_scopes_to_user(self):
        ws = DummyWS()
        session = _session("clerk_user_real")
        with patch.object(main, "_IS_LOCAL_ENV", False), \
             patch.object(
                 main, "_save_trip_sync",
                 return_value={"id": "abc", "gp_slug": "monza"},
             ) as save_sync:
            asyncio.run(main._handle_save_trip(
                ws, {"plan_snapshot": {"x": 1}, "gp_slug": "monza"}, session
            ))
        save_sync.assert_called_once()
        # First positional arg is the user_id the trip is scoped to.
        self.assertEqual(save_sync.call_args.args[0], "clerk_user_real")
        ack = ws.first_of("save_trip_ack")
        self.assertIsNotNone(ack)
        self.assertEqual(ack["data"]["id"], "abc")

    def test_real_user_list_passes_gate(self):
        ws = DummyWS()
        session = _session("clerk_user_real")
        with patch.object(main, "_IS_LOCAL_ENV", False), \
             patch.object(main, "_list_trips_sync", return_value=[]) as list_sync:
            asyncio.run(main._handle_list_trips(ws, session))
        list_sync.assert_called_once_with("clerk_user_real")
        self.assertIsNotNone(ws.first_of("trips_list"))


class DemoUserAllowedOnLocalTests(unittest.TestCase):
    """Local dev (single developer) keeps persistence open for demo-user."""

    def test_demo_user_list_allowed_locally(self):
        ws = DummyWS()
        session = _session("demo-user")
        with patch.object(main, "_IS_LOCAL_ENV", True), \
             patch.object(main, "_list_trips_sync", return_value=[]) as list_sync:
            asyncio.run(main._handle_list_trips(ws, session))
        list_sync.assert_called_once_with("demo-user")
        self.assertIsNone(ws.first_of("error"))
        self.assertIsNotNone(ws.first_of("trips_list"))


if __name__ == "__main__":
    unittest.main()
