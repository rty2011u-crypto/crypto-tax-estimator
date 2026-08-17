"""
Core data model for the crypto tax estimator.

Every transaction, regardless of source (exchange CSV or manually-entered
wallet transfer), gets normalized into a single Transaction record with
this shape. See README.md for the full field-by-field rationale.

IMPORTANT: all money/amount fields use Decimal, never float. Floats lose
precision on decimal values (0.1 cannot be represented exactly in binary
floating point), and those tiny errors compound across thousands of rows
into a final number that's subtly wrong. Decimal avoids this entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class TxType(str, Enum):
    """
    What kind of event this transaction represents.

    A swap (crypto-to-crypto trade) is NEVER stored as a single record —
    it must be split into a SWAP_OUT (the asset given up, a disposal)
    and a SWAP_IN (the asset received, a new cost-basis lot), sharing
    the same timestamp. See README / architecture notes for why.
    """

    BUY = "buy"
    SELL = "sell"
    SWAP_OUT = "swap_out"
    SWAP_IN = "swap_in"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    GIFT_OUT = "gift_out"
    GIFT_IN = "gift_in"
    MINING_INCOME = "mining_income"


# Transaction types that represent a disposal (i.e. they consume FIFO lots
# and can trigger a taxable gain/loss). Kept as a single source of truth
# so fifo_engine.py and gain_loss.py never have to duplicate this list.
DISPOSAL_TYPES = frozenset({TxType.SELL, TxType.SWAP_OUT, TxType.GIFT_OUT})

# Transaction types that create a new cost-basis lot.
ACQUISITION_TYPES = frozenset({TxType.BUY, TxType.SWAP_IN, TxType.GIFT_IN, TxType.MINING_INCOME})


@dataclass
class Transaction:
    id: str
    timestamp: datetime
    type: TxType
    asset: str                       # e.g. "BTC"
    amount: Decimal                  # how much of `asset` moved

    # Value of ONE unit of `asset` in RUB at `timestamp`. For transfers
    # that haven't been classified yet (still in the review queue), this
    # may be None until Step 5 resolves them and Step 4's rate lookup fills it in.
    price_rub: Optional[Decimal] = None

    fee_amount: Decimal = Decimal("0")
    fee_asset: str = ""

    # Destination (for outgoing) or source (for incoming) wallet address.
    # Empty for pure exchange buy/sell with no on-chain movement.
    counterparty_address: str = ""

    # Where this record came from, e.g. "binance", "on_chain_manual".
    # Not used in calculations — purely for debugging / audit trail.
    source: str = ""

    # True until Stage 3 (wallet tagging) + Step 5 (review queue) have
    # both resolved this transaction's classification. A transaction
    # with needs_review=True must NOT be fed into the FIFO engine yet.
    needs_review: bool = False
    review_note: str = ""

    def __post_init__(self) -> None:
        # Fail loudly on the single most common way this schema gets misused:
        # someone passing in a plain float instead of Decimal for a money field.
        for field_name in ("amount", "price_rub", "fee_amount"):
            value = getattr(self, field_name)
            if value is not None and isinstance(value, float):
                raise TypeError(
                    f"Transaction.{field_name} received a float ({value!r}). "
                    "Use Decimal (e.g. Decimal('0.5')) for all money/amount "
                    "fields — floats introduce silent rounding errors."
                )

        if self.amount <= 0:
            raise ValueError(f"Transaction {self.id}: amount must be positive, got {self.amount}")

        if self.type in DISPOSAL_TYPES and not self.needs_review and self.price_rub is None:
            raise ValueError(
                f"Transaction {self.id} is a disposal ({self.type}) but has no "
                "price_rub and is not marked needs_review. A disposal must "
                "either have a known price or be explicitly flagged for review."
            )


@dataclass
class Lot:
    """
    A single 'receipt' in the FIFO queue: some amount of an asset acquired
    at a specific cost. See fifo_engine.py for how these are consumed.
    """

    acquired_at: datetime
    amount: Decimal
    cost_per_unit_rub: Decimal
    source_tx_id: str  # traceability: which Transaction created this lot


@dataclass
class DisposalResult:
    """
    The output of matching one disposal (sell/swap_out/gift_out) against
    the FIFO queue: how much it cost, in total, across however many lots
    it drew from.
    """

    tx_id: str
    asset: str
    disposed_at: datetime
    amount_disposed: Decimal
    proceeds_rub: Decimal          # sale value minus fee, already in RUB
    cost_basis_rub: Decimal        # sum of costs from every lot consumed
    lots_consumed: list = field(default_factory=list)  # list[Lot] portions used

    @property
    def gain_loss_rub(self) -> Decimal:
        return self.proceeds_rub - self.cost_basis_rub
