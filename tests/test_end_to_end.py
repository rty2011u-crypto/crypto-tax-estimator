"""
Integration test using examples/sample_binance.csv and examples/sample_rates.json,
covering the two-leg swap accounting fix: every non-RUB-quoted trade produces
a disposal on BOTH sides, not just an acquisition on the base asset.

Hand calculation (see examples/sample_binance.csv for the raw rows):

Row 0 (funding): BUY 20000 USDT @ 95.00 RUB (RUB-quoted -> single leg,
  pure acquisition, no disposal). Creates one USDT lot: 20000 @ 95.00.

Row 1: BUY 0.5 BTC / dispose 10500 USDT. Both legs priced at their OWN
  market rate on 2026-01-05: BTC = 1,995,000, USDT = 95.00.
  BTC leg (acquisition): fee 0.0005 BTC -> fee_rub = 0.0005*1,995,000 = 997.5
    cost_per_unit = (1,995,000*0.5 + 997.5) / 0.5 = 1,996,995
  USDT leg (disposal): proceeds = 95.00*10500 = 997,500
    cost basis (consumed from the 20000@95.00 lot) = 10500*95.00 = 997,500
    gain = 0 -- deliberately: the USDT market rate here equals its
    acquisition rate, so this leg proves the "zero gain when nothing
    changed" case, not just the "there is a gain" case.
  USDT lot remaining after this row: 9500 @ 95.00.

Row 2: BUY 0.3 BTC / dispose 7500 USDT. Market rates: BTC = 2,412,500,
  USDT = 96.50.
  BTC leg: fee 0.0003 BTC -> fee_rub = 0.0003*2,412,500 = 723.75
    cost_per_unit = (2,412,500*0.3 + 723.75) / 0.3 = 2,414,912.5
  USDT leg: proceeds = 96.50*7500 = 723,750
    cost basis (consumed from the 9500@95.00 remainder) = 7500*95.00 = 712,500
    gain = 723,750 - 712,500 = 11,250
  USDT lot remaining after this row: 2000 @ 95.00.

Row 3: SELL 0.6 BTC / acquire 18600 USDT. Market rates: BTC = 3,013,200,
  USDT = 97.20.
  BTC leg (disposal): fee 0.001 BTC -> fee_rub = 0.001*3,013,200 = 3,013.2
    proceeds = 3,013,200*0.6 - 3,013.2 = 1,804,906.8
    FIFO consumes: all of lot1 (0.5 @ 1,996,995 = 998,497.5)
                   + 0.1 from lot2 (0.1 @ 2,414,912.5 = 241,491.25)
    cost basis = 1,239,988.75
    gain = 1,804,906.8 - 1,239,988.75 = 564,918.05
  USDT leg (acquisition, not a disposal -- no gain/loss to check here).

So engine.process on the full file produces exactly 3 disposals, in
timestamp order: USDT (gain 0), USDT (gain 11,250), BTC (gain 564,918.05).
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import load_rates
from src.fifo_engine import FifoEngine
from src.importers.binance import BinanceImporter
from src.normalize import normalize

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def test_binance_csv_two_leg_swap_accounting_matches_hand_calculation():
    raw_rows = BinanceImporter().import_file(str(EXAMPLES_DIR / "sample_binance.csv"))
    rate_provider = load_rates(str(EXAMPLES_DIR / "sample_rates.json"))
    transactions = normalize(raw_rows, rate_provider)

    engine = FifoEngine(rate_provider=rate_provider)
    results = engine.process(transactions)

    assert len(results) == 3, f"Expected 3 disposals (2 USDT legs + 1 BTC leg), got {len(results)}"

    usdt_results = [r for r in results if r.asset == "USDT"]
    btc_results = [r for r in results if r.asset == "BTC"]
    assert len(usdt_results) == 2
    assert len(btc_results) == 1

    usdt_results.sort(key=lambda r: r.disposed_at)
    first_usdt, second_usdt = usdt_results

    assert first_usdt.proceeds_rub == Decimal("997500.00")
    assert first_usdt.cost_basis_rub == Decimal("997500.00")
    assert first_usdt.gain_loss_rub == Decimal("0.00")

    assert second_usdt.proceeds_rub == Decimal("723750.00")
    assert second_usdt.cost_basis_rub == Decimal("712500.00")
    assert second_usdt.gain_loss_rub == Decimal("11250.00")

    btc_result = btc_results[0]
    assert btc_result.proceeds_rub == Decimal("1804906.8")
    assert btc_result.cost_basis_rub == Decimal("1239988.75")
    assert btc_result.gain_loss_rub == Decimal("564918.05")

    # Remaining holdings sanity check:
    #   USDT: 20000 (funding) - 10500 - 7500 (disposed in rows 1-2)
    #         + 18600 (acquired in row 3's quote leg) = 20600
    #   BTC: lot1 (0.5) fully consumed, lot2 (0.3) has 0.2 left.
    assert engine.remaining_holdings("USDT") == Decimal("20600")
    assert engine.remaining_holdings("BTC") == Decimal("0.2")

    print("test_binance_csv_two_leg_swap_accounting_matches_hand_calculation: PASS")


if __name__ == "__main__":
    test_binance_csv_two_leg_swap_accounting_matches_hand_calculation()
    print("\nAll tests passed.")
