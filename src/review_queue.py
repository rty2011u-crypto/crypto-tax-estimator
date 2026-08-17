"""
Step 5: review queue resolution.

Every transaction that reaches here is still flagged needs_review — its
destination/source address wasn't on the user's known-wallet list. A
human (or a stored prior decision) has to say what it actually was.

IMPORTANT design decision, stated explicitly rather than left implicit:
if an address gets reclassified AFTER the FIFO engine already ran using
the old classification, the correct fix is to re-run the ENTIRE pipeline
from normalize.py onward, not to patch the old result in place.
Incremental "just update this one transaction" logic is a much easier
place to introduce a subtle bug than "just run the whole thing again" —
and this pipeline is cheap enough (seconds, not hours) that a full rerun
is the safer default, not a performance problem worth solving.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

from .exchange_rates import RateProvider
from .models import Transaction, TxType


class Resolution(str, Enum):
    SALE = "sale"
    GIFT_GIVEN = "gift_given"
    GIFT_RECEIVED = "gift_received"
    OWN_WALLET = "own_wallet"
    EXCLUDE = "exclude"


_RESOLUTION_TO_TYPE = {
    Resolution.SALE: TxType.SELL,
    Resolution.GIFT_GIVEN: TxType.GIFT_OUT,
    Resolution.GIFT_RECEIVED: TxType.GIFT_IN,
}


def _normalize_address(addr: str) -> str:
    return addr.strip().lower()


def resolve_transaction(
    tx: Transaction, resolution: Resolution, rate_provider: RateProvider, note: str = ""
) -> Transaction | None:
    """
    Applies a human decision to a flagged transaction. Returns the
    (mutated) Transaction, or None if the resolution was EXCLUDE — the
    caller is responsible for dropping None results from the pipeline.
    """
    if resolution == Resolution.EXCLUDE:
        if not note:
            raise ValueError(
                f"Transaction {tx.id}: EXCLUDE requires a note explaining why "
                "— nothing gets silently dropped without a reason on record."
            )
        return None

    if resolution == Resolution.OWN_WALLET:
        tx.needs_review = False
        tx.review_note = note or "Manually classified as own wallet"
        return tx

    if resolution in (Resolution.SALE, Resolution.GIFT_GIVEN) and tx.type != TxType.TRANSFER_OUT:
        raise ValueError(
            f"Transaction {tx.id}: resolution '{resolution.value}' only makes "
            f"sense for an outgoing transfer, but this transaction is {tx.type}."
        )
    if resolution == Resolution.GIFT_RECEIVED and tx.type != TxType.TRANSFER_IN:
        raise ValueError(
            f"Transaction {tx.id}: 'gift_received' only makes sense for an "
            f"incoming transfer, but this transaction is {tx.type}."
        )

    tx.type = _RESOLUTION_TO_TYPE[resolution]
    # Priced at the asset's own market value on the transaction date —
    # there's no trade price for a wallet transfer, so this is the same
    # market-valuation rule used for mining income (see README).
    tx.price_rub = rate_provider.get_rate(tx.asset, tx.timestamp.date())
    tx.needs_review = False
    tx.review_note = note or f"Manually resolved as {resolution.value}"
    return tx


class AddressClassificationStore:
    """
    Remembers a resolution per address so a recurring counterparty (a
    known exchange deposit address, a friend's wallet) doesn't need to be
    classified by hand every single time it appears.
    """

    def __init__(self) -> None:
        self._classifications: dict[str, Resolution] = {}

    def set_classification(self, address: str, resolution: Resolution) -> None:
        self._classifications[_normalize_address(address)] = resolution

    def get(self, address: str) -> Resolution | None:
        return self._classifications.get(_normalize_address(address))


def save_store(store: AddressClassificationStore, path: str) -> None:
    data = {addr: resolution.value for addr, resolution in store._classifications.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def load_store(path: str) -> AddressClassificationStore:
    store = AddressClassificationStore()
    if not Path(path).exists():
        return store
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for addr, resolution_value in data.items():
        store.set_classification(addr, Resolution(resolution_value))
    return store


def apply_known_addresses(
    transactions: list[Transaction], store: AddressClassificationStore, rate_provider: RateProvider
) -> list[Transaction]:
    """
    Auto-resolves any flagged transaction whose address already has a
    stored classification. Returns the transactions that STILL need a
    human decision — addresses never seen before.
    """
    still_needs_review: list[Transaction] = []

    for tx in transactions:
        if not tx.needs_review:
            continue
        known = store.get(tx.counterparty_address)
        if known is None:
            still_needs_review.append(tx)
            continue
        resolve_transaction(
            tx, known, rate_provider,
            note=f"Auto-applied stored classification for {tx.counterparty_address}",
        )

    return still_needs_review
