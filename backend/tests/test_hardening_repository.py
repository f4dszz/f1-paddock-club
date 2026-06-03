"""Hardening tests: per-user saved-trips quota (BS-02) and Clerk user-deletion
cascade (BS-03), using a fresh in-memory SQLite per test.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ["TEST_DATABASE_URL"] = "sqlite:///:memory:"

import db as db_mod  # noqa: E402
from models import Base, SavedTrip, UserProfile  # noqa: E402
import repository as repo  # noqa: E402


def _save(session, user_id, n):
    for i in range(n):
        repo.save_trip(
            session,
            user_id=user_id,
            gp_slug=f"gp-{i}",
            depart_date=None,
            return_date=None,
            plan_snapshot={"results": []},
            budget_summary={"total": 100},
            active_constraints=None,
        )


class SavedTripsQuotaTests(unittest.TestCase):
    """BS-02: save_trip enforces SAVED_TRIPS_PER_USER_MAX before INSERT."""

    def setUp(self):
        db_mod.rebind_for_tests("sqlite:///:memory:")
        Base.metadata.create_all(db_mod.get_engine())
        self._saved = os.environ.get("SAVED_TRIPS_PER_USER_MAX")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("SAVED_TRIPS_PER_USER_MAX", None)
        else:
            os.environ["SAVED_TRIPS_PER_USER_MAX"] = self._saved

    def test_save_blocked_at_cap(self):
        os.environ["SAVED_TRIPS_PER_USER_MAX"] = "3"
        with db_mod.SessionLocal() as session:
            user = repo.upsert_user(session, clerk_user_id="u-cap", email=None, display_name=None)
            _save(session, user.id, 3)
            self.assertEqual(repo.count_trips(session, user_id=user.id), 3)
            with self.assertRaises(repo.SavedTripQuotaError):
                _save(session, user.id, 1)
            # The over-cap INSERT did not land.
            self.assertEqual(repo.count_trips(session, user_id=user.id), 3)

    def test_cap_is_per_user(self):
        os.environ["SAVED_TRIPS_PER_USER_MAX"] = "1"
        with db_mod.SessionLocal() as session:
            a = repo.upsert_user(session, clerk_user_id="u-a", email=None, display_name=None)
            b = repo.upsert_user(session, clerk_user_id="u-b", email=None, display_name=None)
            _save(session, a.id, 1)
            with self.assertRaises(repo.SavedTripQuotaError):
                _save(session, a.id, 1)
            # Different user has their own quota.
            _save(session, b.id, 1)
            self.assertEqual(repo.count_trips(session, user_id=b.id), 1)

    def test_zero_disables_cap(self):
        os.environ["SAVED_TRIPS_PER_USER_MAX"] = "0"
        with db_mod.SessionLocal() as session:
            user = repo.upsert_user(session, clerk_user_id="u-unbounded", email=None, display_name=None)
            _save(session, user.id, 12)  # cap disabled -> unbounded inserts allowed
            self.assertEqual(repo.count_trips(session, user_id=user.id), 12)

    def test_garbage_env_uses_default(self):
        os.environ["SAVED_TRIPS_PER_USER_MAX"] = "not-an-int"
        self.assertEqual(repo._saved_trips_per_user_max(), 100)

    def test_default_cap_is_100(self):
        os.environ.pop("SAVED_TRIPS_PER_USER_MAX", None)
        self.assertEqual(repo._saved_trips_per_user_max(), 100)


class DeleteUserCascadeTests(unittest.TestCase):
    """BS-03: delete_user_by_clerk_id removes the profile and (FK cascade) trips."""

    def setUp(self):
        db_mod.rebind_for_tests("sqlite:///:memory:")
        # Enable SQLite FK enforcement so ondelete=CASCADE actually fires.
        from sqlalchemy import event

        engine = db_mod.get_engine()

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _rec):  # pragma: no cover - trivial pragma
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        Base.metadata.create_all(engine)

    def test_delete_removes_profile_and_trips(self):
        with db_mod.SessionLocal() as session:
            user = repo.upsert_user(
                session, clerk_user_id="del-me", email="x@y.com", display_name=None
            )
            _save(session, user.id, 2)
            self.assertEqual(repo.count_trips(session, user_id=user.id), 2)

        with db_mod.SessionLocal() as session:
            deleted = repo.delete_user_by_clerk_id(session, clerk_user_id="del-me")
            self.assertTrue(deleted)

        with db_mod.SessionLocal() as session:
            from sqlalchemy import func, select

            self.assertIsNone(
                session.scalar(select(UserProfile).where(UserProfile.clerk_user_id == "del-me"))
            )
            # Cascade removed the trips too.
            remaining = session.scalar(select(func.count()).select_from(SavedTrip))
            self.assertEqual(int(remaining or 0), 0)

    def test_delete_unknown_user_is_idempotent_noop(self):
        with db_mod.SessionLocal() as session:
            self.assertFalse(
                repo.delete_user_by_clerk_id(session, clerk_user_id="never-existed")
            )


if __name__ == "__main__":
    unittest.main()
