"""
Stage 7: report output.

Writes a CSV with one row per disposal event, followed by a yearly
summary section. Tax is only included if a tax_module is passed in —
this is the "optional" toggle from the architecture: someone can use
this tool purely for gain/loss tracking and skip Stage 6 entirely.
"""

from __future__ import annotations

import csv
from decimal import Decimal

from .gain_loss import summarize_by_year
from .models import DisposalResult
from .tax_modules.base import TaxModule


def _fmt(value: Decimal) -> str:
    """Renders a Decimal in plain fixed-point notation. Without this,
    a value that nets to exactly zero (e.g. two equal Decimals with
    different internal scale subtracted from each other) can print as
    '0E-10' — mathematically correct, but confusing in a report meant
    for a human to read."""
    return format(value, "f")


def write_report(
    results: list[DisposalResult], output_path: str, tax_module: TaxModule | None = None
) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        writer.writerow(
            ["date", "asset", "amount_disposed", "proceeds_rub", "cost_basis_rub", "gain_loss_rub"]
        )
        for r in sorted(results, key=lambda r: r.disposed_at):
            writer.writerow(
                [
                    r.disposed_at.date().isoformat(),
                    r.asset,
                    _fmt(r.amount_disposed),
                    _fmt(r.proceeds_rub),
                    _fmt(r.cost_basis_rub),
                    _fmt(r.gain_loss_rub),
                ]
            )

        writer.writerow([])
        gains_by_year = summarize_by_year(results)

        if tax_module is None:
            writer.writerow(["year", "net_gain_loss_rub"])
            for year in sorted(gains_by_year):
                writer.writerow([year, _fmt(gains_by_year[year])])
        else:
            tax_by_year = tax_module.compute_tax_by_year(gains_by_year)
            writer.writerow(["year", "net_gain_loss_rub", f"tax_owed_rub ({tax_module.country_code})"])
            for year in sorted(gains_by_year):
                writer.writerow([year, _fmt(gains_by_year[year]), _fmt(tax_by_year[year])])
