"""Regression tests for the functional-audit fixes.

Each test pins one fixed defect so it cannot silently regress:
  - db URL psycopg3 normalization
  - auth fail-closed on non-local misconfig + JWKS-unavailable -> 503
  - baseline one-way flight -> incomplete quote
  - hard-constraint emptying a category -> incomplete quote
  - constraint extraction no longer misfires on neutral wording
  - "replace X with Y" not-found no longer corrupts an unrelated card
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_ISSUER = "https://test.clerk.example"


class DbUrlNormalizationTests(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ("DATABASE_URL", "TEST_DATABASE_URL")}
        os.environ.pop("TEST_DATABASE_URL", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_bare_postgresql_url_forces_psycopg3_driver(self):
        from db import _database_url
        os.environ["DATABASE_URL"] = "postgresql://u:p@host:5432/db"
        self.assertEqual(_database_url(), "postgresql+psycopg://u:p@host:5432/db")

    def test_legacy_postgres_url_forces_psycopg3_driver(self):
        from db import _database_url
        os.environ["DATABASE_URL"] = "postgres://u:p@host:5432/db"
        self.assertEqual(_database_url(), "postgresql+psycopg://u:p@host:5432/db")

    def test_explicit_driver_left_untouched(self):
        from db import _database_url
        os.environ["DATABASE_URL"] = "postgresql+psycopg://u:p@host:5432/db"
        self.assertEqual(_database_url(), "postgresql+psycopg://u:p@host:5432/db")


class AuthFailClosedTests(unittest.TestCase):
    def setUp(self):
        import auth
        auth.reset_jwks_cache_for_tests()
        for k in ("APP_ENV", "REQUIRE_CLERK_AUTH", "DEMO_ACCESS_TOKEN",
                  "CLERK_JWT_ISSUER", "CLERK_JWKS_URL"):
            os.environ.pop(k, None)
            self.addCleanup(os.environ.pop, k, None)

    def test_non_local_without_any_auth_config_fails_closed_503(self):
        import auth
        from fastapi import HTTPException
        os.environ["APP_ENV"] = "staging"  # non-local, none of the gates set
        with self.assertRaises(HTTPException) as cm:
            auth.require_user(authorization=None)
        self.assertEqual(cm.exception.status_code, 503)

    def test_non_local_without_any_auth_config_closes_ws(self):
        import auth
        os.environ["APP_ENV"] = "staging"

        class _FakeWS:
            query_params: dict = {}
            headers: dict = {}

        with self.assertRaises(auth.AuthError):
            auth.require_user_for_ws(_FakeWS())

    def test_local_without_auth_still_passes_through(self):
        import auth
        os.environ["APP_ENV"] = "test"
        self.assertEqual(auth.require_user(authorization=None), "demo-user")

    def test_jwks_unavailable_maps_to_503_not_500(self):
        import auth
        import httpx
        import jwt
        from fastapi import HTTPException
        from cryptography.hazmat.primitives.asymmetric import rsa

        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = jwt.encode(
            {"iss": _ISSUER, "sub": "u", "exp": int(time.time()) + 60},
            priv, algorithm="RS256", headers={"kid": "kid-1"},
        )
        os.environ["APP_ENV"] = "production"
        os.environ["CLERK_JWT_ISSUER"] = _ISSUER
        auth.reset_jwks_cache_for_tests()
        with mock.patch.object(auth, "_fetch_jwks", side_effect=httpx.ConnectError("boom")):
            with self.assertRaises(HTTPException) as cm:
                auth.require_user(authorization=f"Bearer {token}")
        self.assertEqual(cm.exception.status_code, 503)


class BudgetHonestyTests(unittest.TestCase):
    def _state(self, transport):
        return {
            "currency": "EUR", "budget": 5000,
            "depart_date": "2026-09-04", "return_date": "2026-09-09",
            "tickets": [{"tag": "PICK", "name": "GA", "price": 100, "currency": "EUR"}],
            "transport": transport,
            "hotel": [{"tag": "BUDGET", "name": "X", "price_per_night": 80, "currency": "EUR", "nights": 5}],
        }

    def test_baseline_one_way_flight_is_incomplete(self):
        from tools.recompute import recompute_budget
        q = recompute_budget(self._state([
            {"tag": "OUT", "summary": "o", "detail": "Direct", "price": 400, "currency": "EUR"},
            {"tag": "LOCAL", "summary": "t", "detail": "train", "price": 20, "currency": "EUR"},
        ]))
        self.assertFalse(q["quote_complete"])
        self.assertFalse(q["within_budget"])
        self.assertIn("Flights", q["missing_price_categories"])

    def test_baseline_roundtrip_stays_complete(self):
        from tools.recompute import recompute_budget
        q = recompute_budget(self._state([
            {"tag": "ROUNDTRIP", "summary": "rt", "detail": "Direct", "price": 700, "currency": "EUR"},
            {"tag": "LOCAL", "summary": "t", "detail": "train", "price": 20, "currency": "EUR"},
        ]))
        self.assertTrue(q["quote_complete"])
        self.assertEqual(q["missing_price_categories"], [])


class ConstraintEmptyingTests(unittest.TestCase):
    def test_direct_only_emptying_flights_marks_quote_incomplete(self):
        from refine_constraints import _apply_constraint_filters
        state = {
            "currency": "EUR", "budget": 5000,
            "depart_date": "2026-09-04", "return_date": "2026-09-09",
            "active_constraints": {"direct_only": True},
            "tickets": [{"tag": "PICK", "name": "GA", "price": 100, "currency": "EUR"}],
            "transport": [
                {"tag": "ROUNDTRIP", "summary": "A", "detail": "1 stop(s) - 8h", "price": 900, "currency": "EUR"},
                {"tag": "ROUNDTRIP", "summary": "B", "detail": "1 stop - 9h", "price": 800, "currency": "EUR"},
            ],
            "hotel": [{"tag": "BUDGET", "name": "X", "price_per_night": 80, "currency": "EUR", "nights": 5}],
        }
        _apply_constraint_filters(state)
        self.assertEqual(state["transport"], [])  # both connecting legs removed
        bs = state["budget_summary"]
        self.assertFalse(bs["quote_complete"])
        self.assertFalse(bs["within_budget"])
        self.assertIn("Flights", bs["missing_price_categories"])


class ConstraintExtractionTests(unittest.TestCase):
    def test_neutral_wording_does_not_set_constraints(self):
        from tools._constraints import empty_constraints, merge_constraints
        for neutral in (
            "What is my budget?",
            "increase my budget to 5000",
            "我的预算是多少",
            "Tell me about the Paddock Club experience",
            "how much is the premium ticket?",
        ):
            c = merge_constraints(empty_constraints(), neutral)
            self.assertFalse(c["avoid_luxury"], neutral)
            self.assertEqual(c["budget_strategy"], "balanced", neutral)

    def test_genuine_intent_still_detected(self):
        from tools._constraints import empty_constraints, merge_constraints
        self.assertTrue(merge_constraints(empty_constraints(), "keep it budget-friendly")["avoid_luxury"])
        self.assertEqual(
            merge_constraints(empty_constraints(), "avoid luxury")["budget_strategy"], "cheapest"
        )
        self.assertEqual(
            merge_constraints(empty_constraints(), "I want the VIP experience")["budget_strategy"], "vip"
        )


class ReplaceNotFoundTests(unittest.TestCase):
    def test_absent_target_leaves_cards_untouched(self):
        from refine_editing import apply_line_update
        lines = ["Duomo di Milano — Gothic cathedral", "Navigli District — canals"]
        out = apply_line_update(lines, "Replace Colosseum with Roman Forum", "Tour")
        self.assertEqual(out, lines)

    def test_present_target_still_replaced(self):
        from refine_editing import apply_line_update
        lines = ["Duomo di Milano — Gothic cathedral", "Navigli District — canals"]
        out = apply_line_update(lines, "Replace Duomo with Roman Forum", "Tour")
        self.assertTrue(out[0].startswith("Roman Forum"))
        self.assertEqual(out[1], "Navigli District — canals")


if __name__ == "__main__":
    unittest.main()
