import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tax_modules.russia_ndfl import RussiaNdflModule


def test_below_threshold_flat_13_percent():
    module = RussiaNdflModule()
    # 1,000,000 * 0.13 = 130,000
    result = module.compute_tax_by_year({2026: Decimal("1000000")})
    assert result[2026] == Decimal("130000")
    print("test_below_threshold_flat_13_percent: PASS")


def test_exactly_at_threshold():
    module = RussiaNdflModule()
    # 2,400,000 * 0.13 = 312,000 exactly, no 15% portion applies
    result = module.compute_tax_by_year({2026: Decimal("2400000")})
    assert result[2026] == Decimal("312000")
    print("test_exactly_at_threshold: PASS")


def test_above_threshold_split_bracket():
    module = RussiaNdflModule()
    # From the README worked example: 3,000,000 profit
    # -> 2,400,000 * 0.13 = 312,000
    # -> 600,000 * 0.15 = 90,000
    # -> total 402,000
    result = module.compute_tax_by_year({2026: Decimal("3000000")})
    assert result[2026] == Decimal("402000")
    print("test_above_threshold_split_bracket: PASS")


def test_net_loss_year_produces_zero_tax_not_negative():
    module = RussiaNdflModule()
    result = module.compute_tax_by_year({2026: Decimal("-500000")})
    assert result[2026] == Decimal("0")
    print("test_net_loss_year_produces_zero_tax_not_negative: PASS")


if __name__ == "__main__":
    test_below_threshold_flat_13_percent()
    test_exactly_at_threshold()
    test_above_threshold_split_bracket()
    test_net_loss_year_produces_zero_tax_not_negative()
    print("\nAll tests passed.")
