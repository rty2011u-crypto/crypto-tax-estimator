"""
Stage 2: normalize.

Converts source-specific RawRow objects into the unified Transaction
format everything downstream depends on. This is where quote-currency
prices actually become RUB prices, using a RateProvider (Step 4).

Transfers (transfer_out/transfer_in) are passed through WITHOUT a price —
they either turn out to be non-taxable (Stage 3) or get priced later when
Step 5 resolves them into an actual sale/gift. Pricing them here would be
wasted work at best and a wrong guess at worst, since we don't yet know
if they even need a price.
"""

from __future__ import annotations

from datetime import date as date_type

from .exchange_rates import RateProvider
from .importers.base import RawRow
from .models import Transaction, TxType

NO_PRICE_TYPES = {"transfer_out", "transfer_in"}


def normalize(raw_rows: list[RawRow], rate_provider: RateProvider) -> list[Transaction]:
    transactions: list[Transaction] = []

    for row in raw_rows:
        tx_type = TxType(row.type)  # raises ValueError on an unrecognized type — intentional

        if row.type in NO_PRICE_TYPES:
            price_rub = None
        else:
            on_date: date_type = row.timestamp.date()
            if row.quote_asset == "RUB":
                price_rub = row.quote_price
            else:
                rub_per_quote_unit = rate_provider.get_rate(row.quote_asset, on_date)
                price_rub = row.quote_price * rub_per_quote_unit

        transactions.append(
            Transaction(
                id=row.source_row_id,
                timestamp=row.timestamp,
                type=tx_type,
                asset=row.asset,
                amount=row.amount,
                price_rub=price_rub,
                fee_amount=row.fee_amount,
                fee_asset=row.fee_asset,
                counterparty_address=row.counterparty_address,
                source=row.source,
                needs_review=(row.type in NO_PRICE_TYPES),
                review_note="Wallet transfer — pending Stage 3 address check" if row.type in NO_PRICE_TYPES else "",
            )
        )

    return transactions
