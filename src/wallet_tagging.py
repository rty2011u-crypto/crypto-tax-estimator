"""
Stage 3: wallet tagging.

Checks every transfer_out/transfer_in transaction (which normalize.py
already marked needs_review=True) against a user-supplied set of "these
are my own wallet addresses". A match clears the review flag — it's a
non-taxable internal transfer. Anything that doesn't match STAYS
flagged; this function never clears a transfer just because it looks
plausible. That decision belongs to Step 5 (review_queue.py) and,
ultimately, to a human.
"""

from __future__ import annotations

from .models import Transaction


def _normalize_address(addr: str) -> str:
    return addr.strip().lower()


def tag_wallets(
    transactions: list[Transaction], own_addresses: set[str]
) -> tuple[list[Transaction], list[Transaction]]:
    """
    Returns (all_transactions, still_flagged_transactions). all_transactions
    is the same list, mutated in place so callers can feed it straight into
    later stages; still_flagged_transactions is a convenience view of what
    Step 5 (review_queue.py) still needs to resolve.
    """
    own_normalized = {_normalize_address(a) for a in own_addresses}
    still_flagged: list[Transaction] = []

    for tx in transactions:
        if not tx.needs_review:
            continue
        if tx.counterparty_address and _normalize_address(tx.counterparty_address) in own_normalized:
            tx.needs_review = False
            tx.review_note = "Auto-cleared: transfer between own wallets"
        else:
            tx.review_note = "Unrecognized address — needs manual classification"
            still_flagged.append(tx)

    return transactions, still_flagged
