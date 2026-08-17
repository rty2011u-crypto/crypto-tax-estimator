"""
Hand-calculated FIFO scenario. The expected numbers below were worked out
manually (see comments), not derived from the engine itself — the whole
point of this test is to catch the engine disagreeing with a human.

If you change fifo_engine.py and this test still passes, that's real
evidence you didn't break the core math. If it fails, trust the test,
not the engine.
"""

import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.exchange_rates import StaticRateProvider
from src.fifo_engine import FifoEngine, InsufficientLotsError, UnvaluedFeeError
from src.models import Transaction, TxType


def make_tx(id, ts, type_, amount, price_rub, fee_amount="0", fee_asset=""):
    return Transaction(
        id=id,
        timestamp=datetime.fromisoformat(ts),
        type=type_,
        asset="BTC",
        amount=Decimal(amount),
        price_rub=Decimal(price_rub),
        fee_amount=Decimal(fee_amount),
        fee_asset=fee_asset,
    )


def test_basic_fifo_matches_hand_calculation():
    # Buy 1: 0.5 BTC @ 2,000,000 RUB  -> lot cost = 1,000,000
    # Buy 2: 0.3 BTC @ 2,400,000 RUB  -> lot cost = 720,000
    # Sell:  0.6 BTC @ 3,000,000 RUB
    #
    # FIFO consumes: all of Buy 1 (0.5 @ 2,000,000 = 1,000,000)
    #                + 0.1 from Buy 2 (0.1 @ 2,400,000 = 240,000)
    # Total cost basis = 1,240,000
    # Proceeds = 0.6 * 3,000,000 = 1,800,000
    # Expected gain = 1,800,000 - 1,240,000 = 560,000
    # Expected remaining holdings = 0.3 - 0.1 = 0.2 BTC

    txs = [
        make_tx("buy1", "2026-01-05T00:00:00", TxType.BUY, "0.5", "2000000"),
        make_tx("buy2", "2026-02-10T00:00:00", TxType.BUY, "0.3", "2400000"),
        make_tx("sell1", "2026-03-01T00:00:00", TxType.SELL, "0.6", "3000000"),
    ]

    engine = FifoEngine()
    results = engine.process(txs)

    assert len(results) == 1
    result = results[0]

    assert result.cost_basis_rub == Decimal("1240000")
    assert result.proceeds_rub == Decimal("1800000")
    assert result.gain_loss_rub == Decimal("560000")
    assert engine.remaining_holdings("BTC") == Decimal("0.2")

    print("test_basic_fifo_matches_hand_calculation: PASS")


def test_fee_reduces_gain_on_sale():
    # Same as above but the sale has a 0.001 BTC fee.
    # Fee in RUB = 0.001 * 3,000,000 = 3,000
    # Proceeds = 1,800,000 - 3,000 = 1,797,000
    # Cost basis unchanged = 1,240,000
    # Expected gain = 1,797,000 - 1,240,000 = 557,000

    txs = [
        make_tx("buy1", "2026-01-05T00:00:00", TxType.BUY, "0.5", "2000000"),
        make_tx("buy2", "2026-02-10T00:00:00", TxType.BUY, "0.3", "2400000"),
        make_tx("sell1", "2026-03-01T00:00:00", TxType.SELL, "0.6", "3000000",
                fee_amount="0.001", fee_asset="BTC"),
    ]

    engine = FifoEngine()
    results = engine.process(txs)
    result = results[0]

    assert result.proceeds_rub == Decimal("1797000")
    assert result.gain_loss_rub == Decimal("557000")

    print("test_fee_reduces_gain_on_sale: PASS")


def test_selling_more_than_owned_raises_not_silently_wrong():
    # Only 0.5 BTC ever acquired; trying to sell 0.6 must raise, not
    # produce a confident-looking wrong number.
    txs = [
        make_tx("buy1", "2026-01-05T00:00:00", TxType.BUY, "0.5", "2000000"),
        make_tx("sell1", "2026-03-01T00:00:00", TxType.SELL, "0.6", "3000000"),
    ]

    engine = FifoEngine()
    try:
        engine.process(txs)
        raise AssertionError("Expected InsufficientLotsError, but no exception was raised")
    except InsufficientLotsError:
        print("test_selling_more_than_owned_raises_not_silently_wrong: PASS")


def test_cross_asset_fee_uses_fee_assets_own_market_rate():
    # Sell 0.5 BTC @ 3,000,000 RUB, with a fee of 0.01 BNB.
    # BNB's own market rate on the sale date is looked up separately,
    # NOT derived from the BTC trade price — they're unrelated assets.
    # BNB rate on 2026-03-01 = 40,000 RUB -> fee_rub = 0.01 * 40,000 = 400
    # Proceeds = 0.5 * 3,000,000 - 400 = 1,499,600

    rate_provider = StaticRateProvider({("BNB", date(2026, 3, 1)): Decimal("40000")})

    tx_buy = make_tx("buy1", "2026-01-05T00:00:00", TxType.BUY, "0.5", "2000000")
    tx_sell = make_tx(
        "sell1", "2026-03-01T00:00:00", TxType.SELL, "0.5", "3000000",
        fee_amount="0.01", fee_asset="BNB",
    )

    engine = FifoEngine(rate_provider=rate_provider)
    results = engine.process([tx_buy, tx_sell])

    assert results[0].proceeds_rub == Decimal("1499600")
    print("test_cross_asset_fee_uses_fee_assets_own_market_rate: PASS")


def test_cross_asset_fee_without_rate_provider_still_refuses():
    tx_buy = make_tx("buy1", "2026-01-05T00:00:00", TxType.BUY, "0.5", "2000000")
    tx_sell = make_tx(
        "sell1", "2026-03-01T00:00:00", TxType.SELL, "0.5", "3000000",
        fee_amount="0.01", fee_asset="BNB",
    )

    engine = FifoEngine()  # no rate_provider passed
    try:
        engine.process([tx_buy, tx_sell])
        raise AssertionError("Expected UnvaluedFeeError, but no exception was raised")
    except UnvaluedFeeError:
        print("test_cross_asset_fee_without_rate_provider_still_refuses: PASS")


if __name__ == "__main__":
    test_basic_fifo_matches_hand_calculation()
    test_fee_reduces_gain_on_sale()
    test_selling_more_than_owned_raises_not_silently_wrong()
    test_cross_asset_fee_uses_fee_assets_own_market_rate()
    test_cross_asset_fee_without_rate_provider_still_refuses()
    print("\nAll tests passed.")
