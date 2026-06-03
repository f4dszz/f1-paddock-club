"""test-coverage-1: cross-currency budget math (USD/CNY EUR-pivot).

Covers tools/_currency.py (to_eur / from_eur / convert round-trip +
unknown-currency fail-open) and tools/recompute.recompute_budget run
with a non-EUR state.currency, asserting hand-computed converted totals.

These were a blind spot: every prior budget test hard-coded currency='EUR',
so a wrong rate or inverted division would not be caught.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tools._currency import (  # noqa: E402
    convert,
    from_eur,
    supported_currencies,
    to_eur,
)
from tools.recompute import _FOOD_EUR, _MISC_LOCAL_EUR, _TOUR_EUR, recompute_budget  # noqa: E402

# Rates defined in tools/_currency.py: 1 EUR = X foreign.
_USD = 1.08
_CNY = 7.85


class CurrencyUnitTests(unittest.TestCase):
    def test_eur_is_identity(self):
        self.assertEqual(to_eur(100.0, "EUR"), 100.0)
        self.assertEqual(from_eur(100.0, "EUR"), 100.0)

    def test_to_eur_divides_by_rate(self):
        # 108 USD / 1.08 = 100 EUR
        self.assertAlmostEqual(to_eur(108.0, "USD"), 100.0, places=6)
        # 785 CNY / 7.85 = 100 EUR
        self.assertAlmostEqual(to_eur(785.0, "CNY"), 100.0, places=6)

    def test_from_eur_multiplies_by_rate(self):
        self.assertAlmostEqual(from_eur(100.0, "USD"), 108.0, places=6)
        self.assertAlmostEqual(from_eur(100.0, "CNY"), 785.0, places=6)

    def test_round_trip_to_eur_and_back(self):
        for code in ("USD", "CNY", "EUR"):
            self.assertAlmostEqual(
                from_eur(to_eur(250.0, code), code), 250.0, places=6
            )

    def test_convert_cross_currency_via_eur_pivot(self):
        # 108 USD -> 100 EUR -> 785 CNY
        self.assertAlmostEqual(convert(108.0, "USD", "CNY"), 785.0, places=4)
        # 785 CNY -> 100 EUR -> 108 USD
        self.assertAlmostEqual(convert(785.0, "CNY", "USD"), 108.0, places=4)

    def test_convert_same_currency_is_identity(self):
        self.assertAlmostEqual(convert(42.0, "USD", "USD"), 42.0, places=6)

    def test_case_and_whitespace_normalized(self):
        self.assertAlmostEqual(to_eur(108.0, "  usd  "), 100.0, places=6)
        self.assertAlmostEqual(from_eur(100.0, "cny"), 785.0, places=6)

    def test_unknown_currency_fail_open_returns_amount_unchanged(self):
        # Fail-open: unknown code is treated as EUR (returns amount unchanged).
        self.assertEqual(to_eur(123.45, "JPY"), 123.45)
        self.assertEqual(from_eur(123.45, "GBP"), 123.45)
        # convert through an unknown pivot leg is still pass-through on both legs
        self.assertEqual(convert(50.0, "XXX", "YYY"), 50.0)

    def test_empty_currency_defaults_to_eur(self):
        self.assertEqual(to_eur(99.0, ""), 99.0)
        self.assertEqual(from_eur(99.0, None), 99.0)  # type: ignore[arg-type]

    def test_supported_currencies_set(self):
        self.assertEqual(set(supported_currencies()), {"EUR", "USD", "CNY"})


class RecomputeCrossCurrencyTests(unittest.TestCase):
    """recompute_budget converts every priced item source->target via EUR."""

    def _state(self, currency: str) -> dict:
        # All concrete prices given in EUR so the only conversion is the
        # output denomination (target currency).
        return {
            "currency": currency,
            "budget": 1_000_000,  # huge so 'within budget' is always true
            "gp_date": "2026-09-06",
            "extra_days": 0,  # legacy mode -> Friday..Monday = 3 nights
            "tickets": [
                {"tag": "PICK", "name": "Grandstand", "price": 100.0, "currency": "EUR"},
            ],
            "transport": [
                {"tag": "ROUNDTRIP", "summary": "RT", "price": 200.0, "currency": "EUR"},
                {"tag": "LOCAL", "summary": "metro", "price": 10.0, "currency": "EUR"},
            ],
            "hotel": [
                {"tag": "HOTEL", "name": "Cheap Inn", "price_per_night": 50.0, "currency": "EUR"},
            ],
        }

    def test_eur_baseline_totals(self):
        # nights = 3 (Fri->Mon). Establish the EUR baseline first.
        summary = recompute_budget(self._state("EUR"))
        amounts = {i["name"]: i["amount"] for i in summary["items"]}
        self.assertEqual(amounts["Tickets"], 100.0)
        self.assertEqual(amounts["Flights"], 210.0)  # 200 RT + 10 LOCAL
        self.assertEqual(amounts["Hotel"], 150.0)  # 50 * 3 nights
        self.assertEqual(amounts["Activities"], round(_TOUR_EUR, 2))
        self.assertEqual(amounts["Food (est.)"], round(_FOOD_EUR, 2))
        self.assertEqual(amounts["Local transport"], round(_MISC_LOCAL_EUR, 2))
        expected_total = (
            100.0 + 210.0 + 150.0 + _TOUR_EUR + _FOOD_EUR + _MISC_LOCAL_EUR
        )
        self.assertAlmostEqual(summary["total"], round(expected_total, 2), places=2)
        self.assertEqual(summary["currency"], "EUR")

    def test_usd_total_is_eur_total_times_usd_rate(self):
        summary = recompute_budget(self._state("USD"))
        self.assertEqual(summary["currency"], "USD")
        amounts = {i["name"]: i["amount"] for i in summary["items"]}
        # Every EUR-denominated item is converted EUR->USD (x1.08).
        self.assertAlmostEqual(amounts["Tickets"], round(100.0 * _USD, 2), places=2)
        self.assertAlmostEqual(amounts["Flights"], round(210.0 * _USD, 2), places=2)
        self.assertAlmostEqual(amounts["Hotel"], round(150.0 * _USD, 2), places=2)
        self.assertAlmostEqual(amounts["Activities"], round(_TOUR_EUR * _USD, 2), places=2)
        self.assertAlmostEqual(amounts["Food (est.)"], round(_FOOD_EUR * _USD, 2), places=2)
        expected_total = (
            100.0 + 210.0 + 150.0 + _TOUR_EUR + _FOOD_EUR + _MISC_LOCAL_EUR
        ) * _USD
        self.assertAlmostEqual(summary["total"], round(expected_total, 2), places=1)

    def test_cny_total_is_eur_total_times_cny_rate(self):
        summary = recompute_budget(self._state("CNY"))
        self.assertEqual(summary["currency"], "CNY")
        amounts = {i["name"]: i["amount"] for i in summary["items"]}
        self.assertAlmostEqual(amounts["Tickets"], round(100.0 * _CNY, 2), places=1)
        self.assertAlmostEqual(amounts["Flights"], round(210.0 * _CNY, 2), places=1)
        self.assertAlmostEqual(amounts["Hotel"], round(150.0 * _CNY, 2), places=1)
        expected_total = (
            100.0 + 210.0 + 150.0 + _TOUR_EUR + _FOOD_EUR + _MISC_LOCAL_EUR
        ) * _CNY
        self.assertAlmostEqual(summary["total"], round(expected_total, 2), places=0)

    def test_mixed_source_currency_items_converted_to_target(self):
        # A USD-priced flight in a CNY budget: 108 USD -> 100 EUR -> 785 CNY.
        state = self._state("CNY")
        state["transport"] = [
            {"tag": "ROUNDTRIP", "summary": "RT", "price": 108.0, "currency": "USD"},
        ]
        summary = recompute_budget(state)
        amounts = {i["name"]: i["amount"] for i in summary["items"]}
        self.assertAlmostEqual(amounts["Flights"], round(785.0, 2), places=0)


if __name__ == "__main__":
    unittest.main()
