"""
Shared interface for Stage 6 tax modules. Each country gets its own
module implementing this — see russia_ndfl.py for the only one that
currently exists. This is what makes adding a country later a matter of
adding one new, independently-testable file, not editing existing logic.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol


class TaxModule(Protocol):
    country_code: str

    def compute_tax_by_year(self, gains_by_year: dict[int, Decimal]) -> dict[int, Decimal]:
        """Given net gain/loss per calendar year, returns tax owed per year."""
        ...
