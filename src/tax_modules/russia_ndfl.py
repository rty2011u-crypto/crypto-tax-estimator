"""
Stage 6 (Russia): two-tier NDFL calculation on crypto disposal gains.

Rule, per current research (see README for sourcing): 13% on profit up
to RUB 2,400,000 in a calendar year, 15% on the portion above that.
This applies to the NET gain for the year, not each individual sale.

Explicit, flagged assumption (not verified against a professional
source): this module nets gains and losses within a single calendar
year before applying the bracket, and does NOT implement loss
carryforward into future years. If you have a net loss year, this
module returns zero tax for that year — it does not attempt to bank the
loss against a future year's gains. Verify current FNS guidance on loss
carryforward before relying on this for a real filing.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

THRESHOLD_RUB = Decimal("2400000")
RATE_LOW = Decimal("0.13")
RATE_HIGH = Decimal("0.15")


class RussiaNdflModule:
    country_code = "RU"

    def compute_tax_by_year(self, gains_by_year: dict[int, Decimal]) -> dict[int, Decimal]:
        return {year: self._tax_for_year(gain) for year, gain in gains_by_year.items()}

    @staticmethod
    def _tax_for_year(net_gain_rub: Decimal) -> Decimal:
        if net_gain_rub <= 0:
            return Decimal("0")

        if net_gain_rub <= THRESHOLD_RUB:
            tax = net_gain_rub * RATE_LOW
        else:
            tax = (THRESHOLD_RUB * RATE_LOW) + ((net_gain_rub - THRESHOLD_RUB) * RATE_HIGH)

        return tax.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
