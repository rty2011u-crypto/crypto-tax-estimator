import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.exchange_rates import StaticRateProvider
from src.models import Transaction, TxType
from src.review_queue import AddressClassificationStore, Resolution, apply_known_addresses, resolve_transaction


def make_transfer_out(id, address="bc1qunknown"):
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


def test_resolve_as_sale_sets_type_and_market_price():
    rate_provider = StaticRateProvider({("BTC", date(2026, 3, 1)): Decimal("3000000")})
    tx = make_transfer_out("t1")

    result = resolve_transaction(tx, Resolution.SALE, rate_provider)

    assert result.type == TxType.SELL
    assert result.price_rub == Decimal("3000000")
    assert result.needs_review is False
    print("test_resolve_as_sale_sets_type_and_market_price: PASS")


def test_sale_resolution_on_wrong_direction_raises():
    rate_provider = StaticRateProvider({("BTC", date(2026, 3, 1)): Decimal("3000000")})
    tx = make_transfer_out("t1")
    tx.type = TxType.TRANSFER_IN  # wrong direction for a "sale"

    try:
        resolve_transaction(tx, Resolution.SALE, rate_provider)
        raise AssertionError("Expected ValueError, got no exception")
    except ValueError:
        print("test_sale_resolution_on_wrong_direction_raises: PASS")


def test_exclude_requires_a_note():
    rate_provider = StaticRateProvider({})
    tx = make_transfer_out("t1")

    try:
        resolve_transaction(tx, Resolution.EXCLUDE, rate_provider, note="")
        raise AssertionError("Expected ValueError, got no exception")
    except ValueError:
        print("test_exclude_requires_a_note: PASS")


def test_known_address_auto_resolves_without_asking_again():
    rate_provider = StaticRateProvider({("BTC", date(2026, 3, 1)): Decimal("3000000")})
    store = AddressClassificationStore()
    store.set_classification("bc1qexchange", Resolution.SALE)

    tx1 = make_transfer_out("t1", address="bc1qexchange")
    tx2 = make_transfer_out("t2", address="bc1qexchange")

    still_needs_review = apply_known_addresses([tx1, tx2], store, rate_provider)

    assert still_needs_review == []
    assert tx1.type == TxType.SELL
    assert tx2.type == TxType.SELL
    print("test_known_address_auto_resolves_without_asking_again: PASS")


def test_unknown_address_still_returned_for_review():
    rate_provider = StaticRateProvider({})
    store = AddressClassificationStore()
    tx = make_transfer_out("t1", address="bc1qneverbeforeseen")

    still_needs_review = apply_known_addresses([tx], store, rate_provider)

    assert still_needs_review == [tx]
    print("test_unknown_address_still_returned_for_review: PASS")


if __name__ == "__main__":
    test_resolve_as_sale_sets_type_and_market_price()
    test_sale_resolution_on_wrong_direction_raises()
    test_exclude_requires_a_note()
    test_known_address_auto_resolves_without_asking_again()
    test_unknown_address_still_returned_for_review()
    print("\nAll tests passed.")
