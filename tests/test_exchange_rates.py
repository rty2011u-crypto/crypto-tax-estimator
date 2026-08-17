import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.exchange_rates import RateNotFoundError, StaticRateProvider


def test_exact_date_match():
    provider = StaticRateProvider({("USDT", date(2026, 1, 5)): Decimal("95.00")})
    assert provider.get_rate("USDT", date(2026, 1, 5)) == Decimal("95.00")
    print("test_exact_date_match: PASS")


def test_weekend_fallback_uses_most_recent_prior_rate():
    # Rate published Friday Jan 2; requested for Sunday Jan 4 (no rate published).
    # Should fall back to Friday's rate, not Monday's (there is no Monday rate here).
    provider = StaticRateProvider({("USDT", date(2026, 1, 2)): Decimal("94.50")})
    assert provider.get_rate("USDT", date(2026, 1, 4)) == Decimal("94.50")
    print("test_weekend_fallback_uses_most_recent_prior_rate: PASS")


def test_no_rate_within_lookback_window_raises():
    provider = StaticRateProvider({("USDT", date(2026, 1, 2)): Decimal("94.50")}, max_lookback_days=1)
    try:
        provider.get_rate("USDT", date(2026, 1, 10))
        raise AssertionError("Expected RateNotFoundError, got no exception")
    except RateNotFoundError:
        print("test_no_rate_within_lookback_window_raises: PASS")


def test_rub_always_returns_one():
    provider = StaticRateProvider({})
    assert provider.get_rate("RUB", date(2026, 1, 1)) == Decimal("1")
    print("test_rub_always_returns_one: PASS")


if __name__ == "__main__":
    test_exact_date_match()
    test_weekend_fallback_uses_most_recent_prior_rate()
    test_no_rate_within_lookback_window_raises()
    test_rub_always_returns_one()
    print("\nAll tests passed.")
