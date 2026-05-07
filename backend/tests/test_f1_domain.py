"""Tests for the F1 domain skill — see docs/intelligence-roadmap.md §1.

These tests pin down two contracts:
1. Each scheduled 2026 race has the new domain fields populated.
2. The `_f1_domain` accessor functions degrade gracefully on unknown GPs
   (return None / empty + log a warning, never raise).

We use stdlib `unittest` to match the rest of `backend/tests/`, but the
file is also pytest-collectible (caplog is provided via the bridge).
"""

from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class F1DomainEnrichTests(unittest.TestCase):
    """`enrich()` returns a merged race row + computed session_schedule."""

    def test_enrich_italian_gp_has_circuit_name(self):
        from tools._f1_domain import enrich

        result = enrich("Italian GP")
        self.assertIsNotNone(result)
        self.assertEqual(result["circuit_name"], "Autodromo Nazionale Monza")

    def test_enrich_includes_session_schedule_fri_sat_sun(self):
        from tools._f1_domain import enrich

        result = enrich("Italian GP")
        schedule = result["session_schedule"]
        # Race date is 2026-09-06 (Sunday); Friday and Saturday must back up two days.
        self.assertEqual(schedule["sunday"], "2026-09-06")
        self.assertEqual(schedule["saturday"], "2026-09-05")
        self.assertEqual(schedule["friday"], "2026-09-04")

    def test_enrich_unknown_gp_returns_none_and_warns(self):
        from tools._f1_domain import enrich

        with self.assertLogs("tools._f1_domain", level="WARNING") as caplog:
            self.assertIsNone(enrich("Bogus GP"))
        self.assertTrue(any("Bogus GP" in line for line in caplog.output))

    def test_enrich_returns_shallow_copy_safe_to_mutate(self):
        from tools._f1_domain import enrich

        first = enrich("Italian GP")
        first["circuit_name"] = "tampered"
        second = enrich("Italian GP")
        self.assertEqual(second["circuit_name"], "Autodromo Nazionale Monza")


class F1DomainAccessorTests(unittest.TestCase):
    """Convenience accessors that tools and agents call into."""

    def test_circuit_name_for_known_gp(self):
        from tools._f1_domain import circuit_name_for

        self.assertEqual(circuit_name_for("Monaco GP"), "Circuit de Monaco")

    def test_circuit_name_for_bogus_returns_none_and_warns(self):
        from tools._f1_domain import circuit_name_for

        with self.assertLogs("tools._f1_domain", level="WARNING") as caplog:
            self.assertIsNone(circuit_name_for("Bogus GP"))
        self.assertTrue(any("Bogus GP" in line for line in caplog.output))

    def test_night_race_set_includes_known_night_races(self):
        from tools._f1_domain import night_race_set

        nights = night_race_set()
        for gp in ("Singapore GP", "Las Vegas GP", "Bahrain GP", "Qatar GP", "Saudi Arabian GP"):
            self.assertIn(gp, nights, f"{gp} should be tagged as a night race")

    def test_stay_zones_for_italian_gp_non_empty(self):
        from tools._f1_domain import stay_zones_for

        zones = stay_zones_for("Italian GP")
        self.assertGreaterEqual(len(zones), 1)
        # Monza must appear in the curated list — it's the obvious base.
        self.assertTrue(any("Monza" in z for z in zones))

    def test_stay_zones_for_unknown_gp_returns_empty(self):
        from tools._f1_domain import stay_zones_for

        with self.assertLogs("tools._f1_domain", level="WARNING"):
            self.assertEqual(stay_zones_for("Bogus GP"), [])

    def test_commute_notes_for_known_gp(self):
        from tools._f1_domain import commute_notes_for

        note = commute_notes_for("Italian GP")
        self.assertIsNotNone(note)
        self.assertIsInstance(note, str)
        self.assertGreater(len(note), 5)

    def test_commute_notes_for_unknown_gp_returns_none(self):
        from tools._f1_domain import commute_notes_for

        with self.assertLogs("tools._f1_domain", level="WARNING"):
            self.assertIsNone(commute_notes_for("Bogus GP"))


class F1DataQualityTests(unittest.TestCase):
    """Every scheduled race must carry the new domain fields."""

    def test_all_scheduled_races_have_circuit_and_night_flag(self):
        from tools._race_calendar import all_races

        for race in all_races():
            gp = race["gp_name"]
            self.assertIn("circuit_name", race, f"{gp} missing circuit_name")
            self.assertTrue(race["circuit_name"], f"{gp} circuit_name empty")
            self.assertIn("is_night_race", race, f"{gp} missing is_night_race")
            self.assertIsInstance(race["is_night_race"], bool, f"{gp} is_night_race not bool")
            self.assertIn("stay_zones", race, f"{gp} missing stay_zones")
            self.assertGreaterEqual(len(race["stay_zones"]), 1, f"{gp} stay_zones empty")
            self.assertIn("commute_notes", race, f"{gp} missing commute_notes")
            self.assertTrue(race["commute_notes"], f"{gp} commute_notes empty")

    def test_all_races_shape_unchanged_for_legacy_callers(self):
        """Legacy callers (e.g. `main.get_calendar`) read these keys."""
        from tools._race_calendar import all_races

        legacy_keys = {"gp_name", "city", "country", "race_date", "round"}
        for race in all_races():
            self.assertTrue(
                legacy_keys.issubset(race.keys()),
                f"Race {race.get('gp_name')} missing legacy keys",
            )

    def test_scheduled_race_count_is_22(self):
        """Sanity: still 22 rounds after the data migration."""
        from tools._race_calendar import all_races

        self.assertEqual(len(all_races()), 22)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.WARNING)
    unittest.main()
