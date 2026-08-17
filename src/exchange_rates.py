"""
Step 4: converting a price in some other currency/asset into RUB.

This is used two ways:
  - Fiat/stablecoin -> RUB (e.g. USDT price -> RUB), for normal trades.
  - Crypto asset -> RUB directly (its own market price), for valuing
    mining income and gifts, which don't have a trade price to start from.

Both are conceptually the same operation: "what is 1 unit of X worth in
RUB on date D" — so they share one interface (RateProvider), even though
a real deployment would pull the two from different actual data sources
(Central Bank of Russia for fiat, a crypto price index for assets).

RateNotFoundProvider below is a STUB. It has no real data — it exists so
the rest of the pipeline has something to run and test against. Before
this tool produces a real number for a real filing, this needs to be
replaced with a provider that actually fetches historical rates (e.g.
CBR's published XML feed for fiat, a real price API for crypto assets).
That replacement is explicitly NOT done yet — see README.
"""

from __future__ import annotations

import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol


class RateNotFoundError(Exception):
    """Raised when no rate is available for a currency/asset on or before
    the requested date, within the fallback window. Never silently
    substitutes a different date's rate beyond that window, and never
    substitutes a different asset's rate."""


class RateProvider(Protocol):
    def get_rate(self, symbol: str, on_date: date) -> Decimal:
        """Returns: RUB value of 1 unit of `symbol` on `on_date`."""
        ...


class StaticRateProvider:
    """
    A RateProvider backed by a plain dict, for tests and examples.

    Implements the weekend/holiday fallback rule from the README: if no
    rate is published for the exact date, use the most recent PRIOR
    published rate, searching back up to `max_lookback_days`. This
    matches how the Central Bank of Russia doesn't publish on weekends —
    the fallback is explicit and bounded, not an open-ended guess.
    """

    def __init__(self, rates: dict[tuple[str, date], Decimal], max_lookback_days: int = 7):
        self._rates = rates
        self._max_lookback_days = max_lookback_days

    def get_rate(self, symbol: str, on_date: date) -> Decimal:
        if symbol == "RUB":
            return Decimal("1")

        for delta in range(0, self._max_lookback_days + 1):
            check_date = on_date - timedelta(days=delta)
            if (symbol, check_date) in self._rates:
                return self._rates[(symbol, check_date)]

        raise RateNotFoundError(
            f"No RUB rate found for {symbol} on or before {on_date} "
            f"(searched back {self._max_lookback_days} days). Add this "
            "rate to the provider's data before processing this transaction."
        )


# --- Below this line: real network-backed providers -----------------------
#
# HONESTY NOTE: these were written and built in a sandbox with no network
# access, so the actual HTTP calls have NOT been exercised against a live
# response — only the parsing logic has (see the standalone _parse_* 
# functions and tests/test_exchange_rates.py, which feed them canned
# sample responses). Before relying on either of these for a real number:
# run one live lookup for a date/currency you can independently verify on
# cbr.ru or coingecko.com, and confirm the result matches by hand.


def _parse_cbr_xml(xml_bytes: bytes, symbol: str) -> Decimal | None:
    """
    Parses one day's response from CBR's XML_daily.asp feed and returns
    the RUB value of 1 unit of `symbol`, or None if that currency isn't
    present in this day's data (the caller should then try an earlier
    date, same as the weekend/holiday fallback elsewhere in this file).

    CBR's feed uses comma as the decimal separator and a "Nominal" field
    (rates are sometimes quoted per 10 or per 100 units of a currency,
    not always per 1) — both handled explicitly below rather than assumed.
    """
    root = ET.fromstring(xml_bytes)
    for valute in root.findall("Valute"):
        char_code = valute.findtext("CharCode")
        if char_code == symbol:
            nominal_text = valute.findtext("Nominal")
            value_text = valute.findtext("Value")
            if nominal_text is None or value_text is None:
                return None
            nominal = Decimal(nominal_text)
            value = Decimal(value_text.replace(",", "."))
            return value / nominal
    return None


class CbrRateProvider:
    """
    Fetches historical RUB/foreign-currency rates from the Central Bank of
    Russia's published daily feed. Implements the same weekend/holiday
    fallback as StaticRateProvider.

    NOT LIVE-TESTED — see the honesty note above this class.
    """

    CBR_URL = "https://www.cbr.ru/scripts/XML_daily.asp"

    def __init__(self, max_lookback_days: int = 7, cache: dict[tuple[str, date], Decimal] | None = None):
        self._max_lookback_days = max_lookback_days
        self._cache: dict[tuple[str, date], Decimal] = cache if cache is not None else {}

    def get_rate(self, symbol: str, on_date: date) -> Decimal:
        if symbol == "RUB":
            return Decimal("1")

        for delta in range(0, self._max_lookback_days + 1):
            check_date = on_date - timedelta(days=delta)
            cache_key = (symbol, check_date)
            if cache_key in self._cache:
                return self._cache[cache_key]

            url = f"{self.CBR_URL}?date_req={check_date.strftime('%d/%m/%Y')}"
            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    xml_bytes = response.read()
            except Exception as e:
                raise ConnectionError(f"Failed to fetch CBR rates for {check_date}: {e}") from e

            rate = _parse_cbr_xml(xml_bytes, symbol)
            if rate is not None:
                self._cache[cache_key] = rate
                return rate

        raise RateNotFoundError(
            f"CBR has no published rate for {symbol} on or before {on_date} "
            f"within {self._max_lookback_days} days."
        )


def _parse_coingecko_history_json(data: dict, symbol: str) -> Decimal:
    """
    Parses a CoinGecko /coins/{id}/history response and returns the RUB
    price. Raises RateNotFoundError if the RUB field isn't present (e.g.
    the coin has no data for that date) rather than returning something
    misleading like zero.
    """
    try:
        rub_price = data["market_data"]["current_price"]["rub"]
    except KeyError as e:
        raise RateNotFoundError(
            f"No RUB price found in CoinGecko response for {symbol}."
        ) from e
    return Decimal(str(rub_price))


class CoinGeckoRateProvider:
    """
    Fetches historical crypto-asset market prices in RUB from CoinGecko's
    public API. Used for valuing mining income, gifts, and any asset's
    own market rate (e.g. cross-asset fees) — not for fiat conversion,
    that's CbrRateProvider's job.

    NOT LIVE-TESTED — see the honesty note above CbrRateProvider.

    Known limitation: CoinGecko's free tier rate-limits aggressively. For
    anything beyond a handful of lookups, fetch once and cache (this class
    accepts an external cache dict) rather than one request per transaction.
    """

    API_URL = "https://api.coingecko.com/api/v3/coins/{id}/history"

    # Minimal starter mapping from ticker to CoinGecko's internal id.
    # Extend as needed — an unmapped ticker raises rather than guessing.
    COINGECKO_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin"}

    def __init__(self, cache: dict[tuple[str, date], Decimal] | None = None):
        self._cache: dict[tuple[str, date], Decimal] = cache if cache is not None else {}

    def get_rate(self, symbol: str, on_date: date) -> Decimal:
        if symbol == "RUB":
            return Decimal("1")

        cache_key = (symbol, on_date)
        if cache_key in self._cache:
            return self._cache[cache_key]

        coin_id = self.COINGECKO_IDS.get(symbol)
        if coin_id is None:
            raise RateNotFoundError(
                f"No CoinGecko id mapped for '{symbol}' — add it to "
                "CoinGeckoRateProvider.COINGECKO_IDS before using this symbol."
            )

        date_str = on_date.strftime("%d-%m-%Y")
        url = f"{self.API_URL.format(id=coin_id)}?date={date_str}"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read())
        except Exception as e:
            raise ConnectionError(
                f"Failed to fetch CoinGecko price for {symbol} on {on_date}: {e}"
            ) from e

        rate = _parse_coingecko_history_json(data, symbol)
        self._cache[cache_key] = rate
        return rate
