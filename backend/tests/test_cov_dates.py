"""test-coverage-9: tools/_date_util.py and tools/_trip_dates.py.

Core boundary utilities (feed budget night-counts and external API date
params) had no direct unit tests — off-by-one or format regressions would
be silent. Covers normalize_date (each format, no-year fill, garbage
pass-through), compute_checkout, validate_trip_dates branches, and
compute_trip_dates legacy vs explicit + unparseable fallback + trip_nights
floor.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tools._date_util import compute_checkout, normalize_date  # noqa: E402
from tools._trip_dates import (  # noqa: E402
    _MAX_REASONABLE_NIGHTS,
    compute_trip_dates,
    trip_nights,
    validate_trip_dates,
)


class NormalizeDateTests(unittest.TestCase):
    def test_iso_passthrough(self):
        self.assertEqual(normalize_date("2026-09-07"), "2026-09-07")

    def test_abbrev_month_with_year(self):
        self.assertEqual(normalize_date("Sep 7, 2026"), "2026-09-07")

    def test_full_month_with_year(self):
        self.assertEqual(normalize_date("September 7, 2026"), "2026-09-07")

    def test_abbrev_month_no_comma(self):
        self.assertEqual(normalize_date("Sep 7 2026"), "2026-09-07")

    def test_full_month_no_comma(self):
        self.assertEqual(normalize_date("September 7 2026"), "2026-09-07")

    def test_us_slash_format(self):
        self.assertEqual(normalize_date("9/7/2026"), "2026-09-07")

    def test_no_year_fills_default(self):
        # No year present -> default year 2026 is filled in.
        self.assertEqual(normalize_date("Sep 7"), "2026-09-07")
        self.assertEqual(normalize_date("September 7"), "2026-09-07")

    def test_no_year_respects_custom_default(self):
        self.assertEqual(normalize_date("Sep 7", default_year=2030), "2030-09-07")

    def test_empty_returns_empty(self):
        self.assertEqual(normalize_date(""), "")
        self.assertEqual(normalize_date("   "), "")

    def test_garbage_passes_through_unchanged(self):
        self.assertEqual(normalize_date("not a date"), "not a date")
        # whitespace is stripped on pass-through
        self.assertEqual(normalize_date("  garbage  "), "garbage")


class ComputeCheckoutTests(unittest.TestCase):
    def test_adds_nights(self):
        self.assertEqual(compute_checkout("2026-09-04", 4), "2026-09-08")

    def test_accepts_flexible_checkin(self):
        self.assertEqual(compute_checkout("Sep 4, 2026", 2), "2026-09-06")

    def test_unparseable_checkin_returns_empty(self):
        self.assertEqual(compute_checkout("not a date", 3), "")

    def test_zero_nights(self):
        self.assertEqual(compute_checkout("2026-09-04", 0), "2026-09-04")


class ValidateTripDatesTests(unittest.TestCase):
    def test_both_empty_ok(self):
        ok, reason = validate_trip_dates("2026-09-06", "", "")
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_one_empty_is_error(self):
        ok, reason = validate_trip_dates("2026-09-06", "2026-09-04", "")
        self.assertFalse(ok)
        self.assertIn("both be set", reason)
        ok2, _ = validate_trip_dates("2026-09-06", "", "2026-09-08")
        self.assertFalse(ok2)

    def test_bad_format_is_error(self):
        ok, reason = validate_trip_dates("2026-09-06", "Sep 4", "Sep 8")
        self.assertFalse(ok)
        self.assertIn("YYYY-MM-DD", reason)

    def test_same_day_rejected_as_day_trip(self):
        ok, reason = validate_trip_dates("2026-09-06", "2026-09-06", "2026-09-06")
        self.assertFalse(ok)
        self.assertIn("day-trips", reason)

    def test_depart_after_return_rejected(self):
        ok, reason = validate_trip_dates("2026-09-06", "2026-09-08", "2026-09-04")
        self.assertFalse(ok)
        self.assertIn("strictly before", reason)

    def test_too_many_nights_rejected(self):
        ok, reason = validate_trip_dates(
            "2026-09-06", "2026-09-01", "2026-10-15"  # > 30 nights
        )
        self.assertFalse(ok)
        self.assertIn(str(_MAX_REASONABLE_NIGHTS), reason)

    def test_valid_explicit_range_ok(self):
        ok, reason = validate_trip_dates("2026-09-06", "2026-09-04", "2026-09-08")
        self.assertTrue(ok)
        self.assertEqual(reason, "")


class ComputeTripDatesTests(unittest.TestCase):
    def test_legacy_mode_friday_to_extra_days(self):
        # gp_date is the Sunday race date. outbound = race - 2 (Friday).
        # return = race + extra_days + 1.
        out = compute_trip_dates("2026-09-06", extra_days=2)
        self.assertEqual(out["race_date"], "2026-09-06")
        self.assertEqual(out["outbound_date"], "2026-09-04")  # Friday
        self.assertEqual(out["return_date"], "2026-09-09")  # Sun + 2 + 1
        self.assertEqual(out["hotel_checkin"], "2026-09-04")
        self.assertEqual(out["hotel_checkout"], "2026-09-09")
        self.assertEqual(out["trip_nights"], 5)  # 09-04 .. 09-09

    def test_legacy_mode_zero_extra_days(self):
        out = compute_trip_dates("2026-09-06", extra_days=0)
        self.assertEqual(out["outbound_date"], "2026-09-04")
        self.assertEqual(out["return_date"], "2026-09-07")  # Sun + 0 + 1
        self.assertEqual(out["trip_nights"], 3)

    def test_explicit_mode_takes_user_dates(self):
        out = compute_trip_dates(
            "2026-09-06",
            extra_days=99,  # ignored in explicit mode
            depart_date="2026-09-05",
            return_date="2026-09-10",
        )
        self.assertEqual(out["outbound_date"], "2026-09-05")
        self.assertEqual(out["return_date"], "2026-09-10")
        self.assertEqual(out["trip_nights"], 5)

    def test_explicit_mode_bad_date_falls_open_to_legacy(self):
        out = compute_trip_dates(
            "2026-09-06",
            extra_days=1,
            depart_date="garbage",
            return_date="also-garbage",
        )
        # Falls through to legacy computation (race - 2, race + extra + 1).
        self.assertEqual(out["outbound_date"], "2026-09-04")
        self.assertEqual(out["return_date"], "2026-09-08")

    def test_unparseable_gp_date_returns_safe_skeleton(self):
        out = compute_trip_dates("not a date", extra_days=3)
        # Safe skeleton: all date fields equal the (unparseable) race string,
        # nights = 3 + extra.
        self.assertEqual(out["race_date"], "not a date")
        self.assertEqual(out["outbound_date"], "not a date")
        self.assertEqual(out["trip_nights"], 6)  # 3 + 3

    def test_flexible_gp_date_string_parsed(self):
        out = compute_trip_dates("Sep 6, 2026", extra_days=0)
        self.assertEqual(out["race_date"], "2026-09-06")


class TripNightsTests(unittest.TestCase):
    def test_explicit_dates_drive_nights(self):
        state = {
            "gp_date": "2026-09-06",
            "depart_date": "2026-09-04",
            "return_date": "2026-09-08",
        }
        self.assertEqual(trip_nights(state), 4)

    def test_legacy_extra_days(self):
        self.assertEqual(trip_nights({"gp_date": "2026-09-06", "extra_days": 2}), 5)

    def test_degenerate_state_floors_to_one(self):
        # Unparseable gp_date with extra_days 0 -> skeleton nights = 3, still > 0;
        # force a true zero via explicit same-day dates which yields nights 0,
        # exercising the defensive floor.
        state = {
            "gp_date": "2026-09-06",
            "depart_date": "2026-09-06",
            "return_date": "2026-09-06",
        }
        self.assertEqual(trip_nights(state), 1)


if __name__ == "__main__":
    unittest.main()
