"""
Stage 4: FIFO lot engine.

Maintains a per-asset queue of Lots (purchases), oldest first. Disposals
(sell / swap_out / gift_out) consume from the front of the queue.

Design principle carried over from the architecture discussion: this
engine never silently guesses. If a disposal can't be matched against
enough lots, or a fee can't be confidently valued in RUB, it raises —
it does not produce a number that looks fine but rests on an assumption
nobody signed off on.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal

from .exchange_rates import RateProvider
from .models import ACQUISITION_TYPES, DISPOSAL_TYPES, DisposalResult, Lot, Transaction, TxType


class InsufficientLotsError(Exception):
    """
    Raised when a disposal tries to consume more of an asset than the
    FIFO queue has on record. This means the transaction history is
    incomplete (e.g. a deposit was never logged as an acquisition) —
    it must be fixed in the source data, not silently ignored.
    """


class UnvaluedFeeError(Exception):
    """
    Raised when a transaction's fee is paid in a different asset than
    the transaction itself, and we have no price for that fee asset at
    that timestamp. Valuing a cross-asset fee needs its own price
    lookup (not yet implemented) — see README known limitations.
    """


class UnresolvedTransactionError(Exception):
    """
    Raised if a transaction still flagged needs_review is passed into
    the engine. Review-queue resolution (Step 5) must happen first.
    """


class FifoEngine:
    def __init__(self, rate_provider: RateProvider | None = None) -> None:
        # One queue per asset, e.g. {"BTC": deque([Lot(...), Lot(...)])}
        self._queues: dict[str, deque[Lot]] = {}
        # Used only to value a fee paid in a DIFFERENT asset than the trade
        # itself (e.g. a BNB fee on a BTC trade). Optional: pass None to
        # keep the old strict behavior (any cross-asset fee raises).
        self._rate_provider = rate_provider

    def _queue_for(self, asset: str) -> deque[Lot]:
        return self._queues.setdefault(asset, deque())

    def _fee_in_rub(self, tx: Transaction) -> Decimal:
        """
        Values tx.fee_amount in RUB. The common case — fee paid in the
        same asset as the trade (fee_asset == asset) — uses the trade's
        own price_rub directly. A fee paid in a different asset (e.g. a
        BNB fee on a BTC trade) is valued using that fee asset's OWN
        market rate on the transaction date, via rate_provider — the same
        "value each asset at its own market price" principle used for
        mining income and gifts. If no rate_provider was given, this
        still refuses rather than guessing.
        """
        if tx.fee_amount == 0:
            return Decimal("0")
        if tx.fee_asset in ("", tx.asset):
            return tx.fee_amount * tx.price_rub
        if self._rate_provider is None:
            raise UnvaluedFeeError(
                f"Transaction {tx.id}: fee is in {tx.fee_asset}, but transaction "
                f"asset is {tx.asset}, and no rate_provider was given to this "
                "FifoEngine to look up the fee asset's own market rate. Pass a "
                "rate_provider, or resolve this fee manually."
            )
        rate = self._rate_provider.get_rate(tx.fee_asset, tx.timestamp.date())
        return tx.fee_amount * rate

    def _acquire(self, tx: Transaction) -> None:
        fee_rub = self._fee_in_rub(tx)
        total_cost = (tx.price_rub * tx.amount) + fee_rub
        cost_per_unit = total_cost / tx.amount
        lot = Lot(
            acquired_at=tx.timestamp,
            amount=tx.amount,
            cost_per_unit_rub=cost_per_unit,
            source_tx_id=tx.id,
        )
        self._queue_for(tx.asset).append(lot)

    def _dispose(self, tx: Transaction) -> DisposalResult:
        queue = self._queue_for(tx.asset)
        remaining_to_sell = tx.amount
        cost_basis = Decimal("0")
        lots_consumed: list[Lot] = []

        while remaining_to_sell > 0:
            if not queue:
                raise InsufficientLotsError(
                    f"Transaction {tx.id}: trying to dispose of {tx.amount} "
                    f"{tx.asset}, but the FIFO queue ran out with "
                    f"{remaining_to_sell} still unaccounted for. This means "
                    "the transaction history is missing an acquisition — "
                    "check for a missing import or misclassified transfer."
                )

            front = queue[0]

            if front.amount <= remaining_to_sell:
                # Consume the whole front lot.
                cost_basis += front.amount * front.cost_per_unit_rub
                lots_consumed.append(front)
                remaining_to_sell -= front.amount
                queue.popleft()
            else:
                # Partially consume the front lot; leave the remainder in place.
                consumed_amount = remaining_to_sell
                cost_basis += consumed_amount * front.cost_per_unit_rub
                lots_consumed.append(
                    Lot(
                        acquired_at=front.acquired_at,
                        amount=consumed_amount,
                        cost_per_unit_rub=front.cost_per_unit_rub,
                        source_tx_id=front.source_tx_id,
                    )
                )
                front.amount -= consumed_amount
                remaining_to_sell = Decimal("0")

        fee_rub = self._fee_in_rub(tx)
        proceeds = (tx.price_rub * tx.amount) - fee_rub

        return DisposalResult(
            tx_id=tx.id,
            asset=tx.asset,
            disposed_at=tx.timestamp,
            amount_disposed=tx.amount,
            proceeds_rub=proceeds,
            cost_basis_rub=cost_basis,
            lots_consumed=lots_consumed,
        )

    def process(self, transactions: list[Transaction]) -> list[DisposalResult]:
        """
        Processes transactions in timestamp order and returns one
        DisposalResult per disposal event. Acquisitions update the
        internal queues but produce no direct output (their effect
        shows up later, when something disposes of them).
        """
        for tx in transactions:
            if tx.needs_review:
                raise UnresolvedTransactionError(
                    f"Transaction {tx.id} is still flagged needs_review. "
                    "Resolve it (Step 5) before running the FIFO engine."
                )

        ordered = sorted(transactions, key=lambda t: t.timestamp)

        results: list[DisposalResult] = []
        for tx in ordered:
            if tx.type in ACQUISITION_TYPES:
                self._acquire(tx)
            elif tx.type in DISPOSAL_TYPES:
                results.append(self._dispose(tx))
            elif tx.type in (TxType.TRANSFER_OUT, TxType.TRANSFER_IN):
                # Transfers between the user's own wallets don't touch cost
                # basis at all — by the time a transaction reaches this
                # engine it should already be resolved as either a genuine
                # non-taxable transfer (skip) or reclassified into one of
                # the types above by Step 5. This branch intentionally
                # does nothing.
                continue
            else:
                raise ValueError(f"Transaction {tx.id}: unhandled type {tx.type}")

        return results

    def remaining_holdings(self, asset: str) -> Decimal:
        """Sum of amounts still sitting in the queue for `asset` — useful for
        sanity-checking against a known real-world balance."""
        return sum((lot.amount for lot in self._queue_for(asset)), Decimal("0"))
