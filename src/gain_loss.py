"""
Stage 5 aggregation: rolls individual DisposalResult rows (one per sale/
swap_out/gift_out) into yearly totals, since Russian NDFL is calculated
on a calendar-year basis, not per-transaction.
"""

from __future__ import annotations

from decimal import Decimal

from .models import DisposalResult


def summarize_by_year(results: list[DisposalResult]) -> dict[int, Decimal]:
    totals: dict[int, Decimal] = {}
    for r in results:
        year = r.disposed_at.year
        totals[year] = totals.get(year, Decimal("0")) + r.gain_loss_rub
    return totals


def summarize_by_asset_and_year(results: list[DisposalResult]) -> dict[tuple[str, int], Decimal]:
    totals: dict[tuple[str, int], Decimal] = {}
    for r in results:
        key = (r.asset, r.disposed_at.year)
        totals[key] = totals.get(key, Decimal("0")) + r.gain_loss_rub
    return totals
