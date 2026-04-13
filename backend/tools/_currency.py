"""Currency conversion for budget computation.

Converts prices from their source currency to a target currency (default EUR).
Uses fixed exchange rates — good enough for budget estimation. Live rates
would add an API dependency for marginal accuracy gain.

Supported currencies: EUR, USD, CNY.
Add more by extending _RATES_TO_EUR.

Design: all rates are defined relative to EUR (1 EUR = X foreign).
To convert FROM foreign TO EUR: amount / rate.
To convert FROM EUR TO foreign: amount * rate.
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

# 1 EUR = X units of foreign currency (approximate, updated 2026-04)
_RATES_TO_EUR: dict[str, float] = {
    "EUR": 1.0,
    "USD": 1.08,   # 1 EUR ≈ 1.08 USD
    "CNY": 7.85,   # 1 EUR ≈ 7.85 CNY
}


def to_eur(amount: float, currency: str) -> float:
    """Convert an amount from any supported currency to EUR.

    Args:
        amount: The price in source currency.
        currency: Source currency code (EUR, USD, CNY).

    Returns:
        Amount in EUR. If currency is unknown, returns amount unchanged
        and logs a warning (fail-open: better to compute an approximate
        budget than to crash).
    """
    code = currency.upper().strip() if currency else "EUR"
    rate = _RATES_TO_EUR.get(code)
    if rate is None:
        logger.warning("Unknown currency '%s', treating as EUR", currency)
        return amount
    return amount / rate


def from_eur(amount: float, currency: str) -> float:
    """Convert an amount from EUR to a target currency."""
    code = currency.upper().strip() if currency else "EUR"
    rate = _RATES_TO_EUR.get(code)
    if rate is None:
        logger.warning("Unknown currency '%s', treating as EUR", currency)
        return amount
    return amount * rate


def convert(amount: float, from_currency: str, to_currency: str) -> float:
    """Convert between any two supported currencies via EUR."""
    eur = to_eur(amount, from_currency)
    return from_eur(eur, to_currency)


def supported_currencies() -> list[str]:
    """Return list of supported currency codes."""
    return list(_RATES_TO_EUR.keys())
