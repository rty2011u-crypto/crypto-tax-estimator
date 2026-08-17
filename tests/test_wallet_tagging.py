import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import Transaction, TxType
from src.wallet_tagging import tag_wallets


def make_transfer(id, address):
    return Transaction(
        id=id,
        timestamp=datetime(2026, 3, 1),
        type=TxType.TRANSFER_OUT,
        asset="BTC",
        amount=Decimal("0.1"),
        price_rub=None,
        counterparty_address=address,
        needs_review=True,
    )


def test_known_address_gets_auto_cleared():
    tx = make_transfer("t1", "bc1qmine")
    all_tx, flagged = tag_wallets([tx], own_addresses={"bc1qmine"})
    assert tx.needs_review is False
    assert flagged == []
    print("test_known_address_gets_auto_cleared: PASS")


def test_unknown_address_stays_flagged_never_guessed():
    tx = make_transfer("t2", "bc1qsomeoneelse")
    all_tx, flagged = tag_wallets([tx], own_addresses={"bc1qmine"})
    assert tx.needs_review is True
    assert flagged == [tx]
    print("test_unknown_address_stays_flagged_never_guessed: PASS")


def test_address_matching_is_case_insensitive():
    tx = make_transfer("t3", "BC1QMINE")
    all_tx, flagged = tag_wallets([tx], own_addresses={"bc1qmine"})
    assert tx.needs_review is False
    print("test_address_matching_is_case_insensitive: PASS")


if __name__ == "__main__":
    test_known_address_gets_auto_cleared()
    test_unknown_address_stays_flagged_never_guessed()
    test_address_matching_is_case_insensitive()
    print("\nAll tests passed.")
