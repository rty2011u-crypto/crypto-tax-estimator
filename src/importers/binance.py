"""
Binance spot trade history importer.

Column format verified against real-world exports:
    Date(UTC), Pair, Side, Price, Executed, Amount, Fee
with number+ticker glued together (no space, no separate Fee Coin column) —
see git history / README for how this was confirmed.

CORE ACCOUNTING RULE (this is the important part, read it before changing
anything here): a trade quoted in RUB is a single taxable event — buying
crypto with rubles is a pure acquisition, selling crypto for rubles is a
pure disposal, because rubles are money, not property, under Russian law.

A trade quoted in ANYTHING ELSE — a stablecoin (USDT, USDC, BUSD) or
another crypto asset (ETHBTC) — is a SWAP: you dispose of one digital
currency and acquire another, and Russian guidance treats digital-currency
swaps as taxable events. This was a real bug in an earlier version of this
importer: it treated stablecoin-quoted trades as if the stablecoin side
didn't matter, which silently under-counted taxable disposals. Every
non-RUB-quoted row here now produces TWO transactions (a base leg and a
quote leg), each priced at ITS OWN independent market rate on that date —
not derived from the other leg's trade price — for the same reason mining
income and gifts are priced independently: each asset's fair market value
at the moment of the event is the actual legal question, not what the
counterparty in one specific trade happened to charge.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from decimal import Decimal

from .base import RawRow

EXPECTED_COLUMNS = {"Date(UTC)", "Pair", "Side", "Price", "Executed", "Amount", "Fee"}

# Matches a decimal number (with optional thousands commas) immediately
# followed by an alphabetic ticker, e.g. "0.50000000BTC" or "3,000.12USD".
_NUMBER_AND_SUFFIX_RE = re.compile(r'^\s*"?([\d,]+\.?\d*)([A-Za-z]*)"?\s*$')


class MismatchedPairError(Exception):
    """Raised when the base+quote assets parsed from Executed/Amount don't
    reconstruct the Pair column exactly. Refuse to guess which is right —
    surface the row for a human to check."""


def _parse_number_and_suffix(value: str) -> tuple[Decimal, str]:
    match = _NUMBER_AND_SUFFIX_RE.match(value)
    if not match:
        raise ValueError(f"Could not parse a number+ticker from '{value}'")
    number_str, suffix = match.groups()
    return Decimal(number_str.replace(",", "")), suffix


class BinanceImporter:
    def import_file(self, path: str) -> list[RawRow]:
        rows: list[RawRow] = []

        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            missing = EXPECTED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise ValueError(
                    f"File {path} is missing expected columns {missing}. "
                    f"Found columns: {reader.fieldnames}."
                )

            for i, row in enumerate(reader):
                executed_amount, base_asset = _parse_number_and_suffix(row["Executed"])
                quote_amount, quote_asset = _parse_number_and_suffix(row["Amount"])

                if row["Pair"] != base_asset + quote_asset:
                    raise MismatchedPairError(
                        f"Row {i} in {path}: Pair column says '{row['Pair']}' but "
                        f"Executed/Amount suggest base='{base_asset}', "
                        f"quote='{quote_asset}'. Refusing to guess — check by hand."
                    )

                side = row["Side"].strip().upper()
                if side not in ("BUY", "SELL"):
                    raise ValueError(f"Row {i} in {path}: unrecognized Side '{row['Side']}'")

                fee_amount, fee_asset = Decimal("0"), ""
                if row["Fee"].strip():
                    fee_amount, fee_asset = _parse_number_and_suffix(row["Fee"])

                price = Decimal(row["Price"].replace(",", "").strip().strip('"'))
                timestamp = datetime.strptime(row["Date(UTC)"], "%Y-%m-%d %H:%M:%S")
                row_id = f"binance:{path}:{i}"

                if quote_asset == "RUB":
                    # Single-leg: rubles aren't a taxable digital currency.
                    tx_type = "buy" if side == "BUY" else "sell"
                    rows.append(
                        RawRow(
                            source_row_id=row_id,
                            timestamp=timestamp,
                            type=tx_type,
                            asset=base_asset,
                            amount=executed_amount,
                            quote_asset="RUB",
                            quote_price=price,
                            fee_amount=fee_amount,
                            fee_asset=fee_asset,
                            source="binance",
                        )
                    )
                else:
                    # Two-leg swap. BUY: acquire base, dispose quote.
                    # SELL: dispose base, acquire quote.
                    base_type, quote_type = ("swap_in", "swap_out") if side == "BUY" else ("swap_out", "swap_in")

                    # Fee is attached to the base leg only (documented
                    # assumption — there's one fee per trade row, not one
                    # per leg). FifoEngine values it at the fee asset's own
                    # market rate regardless of which leg it's attached to,
                    # so this placement doesn't change the resulting number.
                    rows.append(
                        RawRow(
                            source_row_id=f"{row_id}:base",
                            timestamp=timestamp,
                            type=base_type,
                            asset=base_asset,
                            amount=executed_amount,
                            quote_asset=base_asset,  # self-priced via its own market rate
                            quote_price=Decimal("1"),
                            fee_amount=fee_amount,
                            fee_asset=fee_asset,
                            source="binance",
                        )
                    )
                    rows.append(
                        RawRow(
                            source_row_id=f"{row_id}:quote",
                            timestamp=timestamp,
                            type=quote_type,
                            asset=quote_asset,
                            amount=quote_amount,
                            quote_asset=quote_asset,  # self-priced via its own market rate
                            quote_price=Decimal("1"),
                            fee_amount=Decimal("0"),
                            fee_asset="",
                            source="binance",
                        )
                    )

        return rows
