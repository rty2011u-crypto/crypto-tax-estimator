"""
Manual wallet importer.

Reads a JSON file of hand-entered on-chain events — transfers, mining
income, gifts — that don't come from an exchange CSV. Expected format is
a JSON list of objects:

[
  {"id": "w1", "timestamp": "2026-03-01T00:00:00", "type": "transfer_out",
   "asset": "BTC", "amount": "0.1", "counterparty_address": "bc1q..."},
  {"id": "w2", "timestamp": "2026-04-15T00:00:00", "type": "mining_income",
   "asset": "BTC", "amount": "0.01"}
]

For transfer_out/transfer_in: no price is needed at import time. These
either turn out to be non-taxable (Stage 3 matches the address against
your own-wallet list) or get priced later when Step 5 resolves them as
an actual sale/gift.

For mining_income/gift_in/gift_out: these DO need a RUB value, since
they're valued at market price on the date of the event, not a trade
price. quote_asset is set to the asset itself so normalize.py looks up
"how much is 1 unit of this asset worth in RUB on this date" via
exchange_rates.py, the same mechanism used for fiat conversion.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from .base import RawRow

NO_PRICE_NEEDED_TYPES = {"transfer_out", "transfer_in"}
MARKET_VALUED_TYPES = {"mining_income", "gift_in", "gift_out"}


class ManualWalletImporter:
    def import_file(self, path: str) -> list[RawRow]:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)

        rows: list[RawRow] = []
        for entry in entries:
            entry_type = entry["type"]

            if entry_type in NO_PRICE_NEEDED_TYPES:
                quote_asset = ""
                quote_price = Decimal("0")
            elif entry_type in MARKET_VALUED_TYPES:
                quote_asset = entry["asset"]
                quote_price = Decimal("1")
            else:
                raise ValueError(
                    f"Entry {entry.get('id')}: unrecognized type '{entry_type}' "
                    f"for manual wallet import. Expected one of "
                    f"{NO_PRICE_NEEDED_TYPES | MARKET_VALUED_TYPES}."
                )

            rows.append(
                RawRow(
                    source_row_id=f"manual:{path}:{entry['id']}",
                    timestamp=datetime.fromisoformat(entry["timestamp"]),
                    type=entry_type,
                    asset=entry["asset"],
                    amount=Decimal(entry["amount"]),
                    quote_asset=quote_asset,
                    quote_price=quote_price,
                    fee_amount=Decimal(entry.get("fee_amount", "0")),
                    fee_asset=entry.get("fee_asset", ""),
                    counterparty_address=entry.get("counterparty_address", ""),
                    source="manual_wallet",
                )
            )

        return rows
