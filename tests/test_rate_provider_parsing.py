"""
Tests the PARSING logic of CbrRateProvider and CoinGeckoRateProvider
against canned sample responses. This does NOT test the actual network
calls — this sandbox has no network access. Before trusting these
providers on a real filing, also run a real, live lookup and check it
by hand — these tests only prove the parsing is correct for the response
SHAPE assumed here, not that a live call will succeed or that the
assumed shape hasn't changed.
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.exchange_rates import RateNotFoundError, _parse_cbr_xml, _parse_coingecko_history_json

# Sample shaped after CBR's real XML_daily.asp structure: comma decimal
# separator, and a non-1 Nominal (JPY is quoted per 100 units, not per 1).
SAMPLE_CBR_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ValCurs Date="15.03.2026" name="Foreign Currency Market">
    <Valute ID="R01235">
        <NumCode>840</NumCode>
        <CharCode>USD</CharCode>
        <Nominal>1</Nominal>
        <Name>Doll SShA</Name>
        <Value>95,1234</Value>
    </Valute>
    <Valute ID="R01820">
        <NumCode>392</NumCode>
        <CharCode>JPY</CharCode>
        <Nominal>100</Nominal>
        <Name>Iena</Name>
        <Value>63,5000</Value>
    </Valute>
</ValCurs>
"""

SAMPLE_COINGECKO_JSON = {
    "id": "bitcoin",
    "symbol": "btc",
    "market_data": {
        "current_price": {
            "usd": 65000.12,
            "rub": 6180000.55,
        }
    },
}


def test_cbr_parses_simple_nominal_one_currency():
    rate = _parse_cbr_xml(SAMPLE_CBR_XML, "USD")
    assert rate == Decimal("95.1234")
    print("test_cbr_parses_simple_nominal_one_currency: PASS")


def test_cbr_correctly_divides_by_nominal_when_not_one():
    # JPY is quoted per 100 units: Value=63.50 for Nominal=100 means
    # 1 JPY = 0.635 RUB, NOT 63.50 RUB. Getting this wrong silently
    # produces a number 100x too large — exactly the kind of bug this
    # test exists to catch.
    rate = _parse_cbr_xml(SAMPLE_CBR_XML, "JPY")
    assert rate == Decimal("0.635")
    print("test_cbr_correctly_divides_by_nominal_when_not_one: PASS")


def test_cbr_returns_none_for_currency_not_in_response():
    rate = _parse_cbr_xml(SAMPLE_CBR_XML, "GBP")
    assert rate is None
    print("test_cbr_returns_none_for_currency_not_in_response: PASS")


def test_coingecko_parses_rub_price():
    rate = _parse_coingecko_history_json(SAMPLE_COINGECKO_JSON, "BTC")
    assert rate == Decimal("6180000.55")
    print("test_coingecko_parses_rub_price: PASS")


def test_coingecko_missing_rub_raises_not_silently_wrong():
    malformed = {"market_data": {"current_price": {"usd": 65000.12}}}  # no "rub" key
    try:
        _parse_coingecko_history_json(malformed, "BTC")
        raise AssertionError("Expected RateNotFoundError, got no exception")
    except RateNotFoundError:
        print("test_coingecko_missing_rub_raises_not_silently_wrong: PASS")


if __name__ == "__main__":
    test_cbr_parses_simple_nominal_one_currency()
    test_cbr_correctly_divides_by_nominal_when_not_one()
    test_cbr_returns_none_for_currency_not_in_response()
    test_coingecko_parses_rub_price()
    test_coingecko_missing_rub_raises_not_silently_wrong()
    print("\nAll tests passed.")
