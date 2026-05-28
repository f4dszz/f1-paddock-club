"""Repository round-trip tests using a fresh in-memory SQLite per test."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Make sure tests find the backend modules and use an isolated SQLite.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ["TEST_DATABASE_URL"] = "sqlite:///:memory:"

import db as db_mod  # noqa: E402
from models import (  # noqa: E402,F401
    Base,
    SavedConstraints,
    SavedTrip,
    UserProfile,
)
import repository as repo  # noqa: E402


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        # Rebind to a fresh in-memory engine for each test for isolation.
        db_mod.rebind_for_tests("sqlite:///:memory:")
        Base.metadata.create_all(db_mod.get_engine())

    def test_upsert_user_creates_then_updates(self):
        with db_mod.SessionLocal() as session:
            row = repo.upsert_user(session, clerk_user_id="u1", email="a@b.com", display_name="A")
            self.assertEqual(row.clerk_user_id, "u1")
            row2 = repo.upsert_user(session, clerk_user_id="u1", email="a2@b.com", display_name="A")
            self.assertEqual(row.id, row2.id)
            self.assertEqual(row2.email, "a2@b.com")

    def test_save_and_list_trips(self):
        with db_mod.SessionLocal() as session:
            user = repo.upsert_user(session, clerk_user_id="u2", email=None, display_name=None)
            repo.save_trip(
                session,
                user_id=user.id,
                gp_slug="italian-gp-2026",
                depart_date=None,
                return_date=None,
                plan_snapshot={"results": []},
                budget_summary={"total": 1000},
                active_constraints={"direct_only": True},
            )
            trips = repo.list_trips(session, user_id=user.id)
            self.assertEqual(len(trips), 1)
            self.assertEqual(trips[0].gp_slug, "italian-gp-2026")
            self.assertEqual(trips[0].plan_snapshot, {"results": []})

    def test_get_trip_scoped_to_user(self):
        with db_mod.SessionLocal() as session:
            u1 = repo.upsert_user(session, clerk_user_id="ua", email=None, display_name=None)
            u2 = repo.upsert_user(session, clerk_user_id="ub", email=None, display_name=None)
            t = repo.save_trip(
                session,
                user_id=u1.id,
                gp_slug="x",
                depart_date=None,
                return_date=None,
                plan_snapshot={},
                budget_summary=None,
                active_constraints=None,
            )
            self.assertIsNotNone(repo.get_trip(session, trip_id=t.id, user_id=u1.id))
            self.assertIsNone(repo.get_trip(session, trip_id=t.id, user_id=u2.id))

    def test_delete_trip_only_owner(self):
        with db_mod.SessionLocal() as session:
            u1 = repo.upsert_user(session, clerk_user_id="ud", email=None, display_name=None)
            u2 = repo.upsert_user(session, clerk_user_id="ue", email=None, display_name=None)
            t = repo.save_trip(
                session,
                user_id=u1.id,
                gp_slug="x",
                depart_date=None,
                return_date=None,
                plan_snapshot={},
                budget_summary=None,
                active_constraints=None,
            )
            # other user cannot delete
            self.assertFalse(repo.delete_trip(session, trip_id=t.id, user_id=u2.id))
            # owner can
            self.assertTrue(repo.delete_trip(session, trip_id=t.id, user_id=u1.id))
            # second delete returns False
            self.assertFalse(repo.delete_trip(session, trip_id=t.id, user_id=u1.id))

    def test_constraints_upsert_keeps_one_row_per_user(self):
        with db_mod.SessionLocal() as session:
            user = repo.upsert_user(session, clerk_user_id="uc", email=None, display_name=None)
            repo.upsert_constraints(session, user_id=user.id, defaults={"direct_only": True})
            repo.upsert_constraints(session, user_id=user.id, defaults={"direct_only": False})
            row = repo.get_constraints(session, user_id=user.id)
            self.assertIsNotNone(row)
            self.assertEqual(row.defaults, {"direct_only": False})


if __name__ == "__main__":
    unittest.main()
