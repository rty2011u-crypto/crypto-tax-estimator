"""
Base interface for importers.

Importers do NOT produce Transaction objects directly. They produce
RawRow objects, because a raw exchange row's price is usually quoted in
whatever currency the trade happened in (USDT, USD, RUB...) — not
necessarily RUB. Converting that into a final RUB-denominated
Transaction is normalize.py's job (Stage 2), using exchange_rates.py.

Keeping this as two steps means an importer only needs to know its own
source's file format, not the Central Bank of Russia's rate history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass
class RawRow:
    source_row_id: str
    timestamp: datetime
    type: str              # matches a TxType value, e.g. "buy" / "sell"
    asset: str
    amount: Decimal
    quote_asset: str       # e.g. "USDT", "RUB", or another crypto asset
    quote_price: Decimal   # price of 1 unit of `asset` in `quote_asset`
    fee_amount: Decimal = Decimal("0")
    fee_asset: str = ""
    counterparty_address: str = ""
    source: str = ""


class Importer(Protocol):
    def import_file(self, path: str) -> list[RawRow]:
        ...
