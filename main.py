"""
CLI entry point. Ties Stages 1-7 together.

Current behavior on unresolved transfers (deliberate MVP scope, not an
oversight): if any wallet transfer can't be auto-cleared or auto-resolved
from a stored address classification, the run STOPS and lists them
instead of guessing or skipping silently. Resolving them interactively
in the terminal is a reasonable next feature, but a half-built
interactive prompt is worse than an honest stop here — see
tests/test_review_queue.py for how to resolve them in code today.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.exchange_rates import RateNotFoundError, StaticRateProvider
from src.fifo_engine import FifoEngine
from src.importers.base import RawRow
from src.importers.binance import BinanceImporter
from src.importers.manual_wallet import ManualWalletImporter
from src.normalize import normalize
from src.report import write_report
from src.review_queue import Resolution, apply_known_addresses, load_store, resolve_transaction, save_store
from src.tax_modules.russia_ndfl import RussiaNdflModule
from src.wallet_tagging import tag_wallets

_RESOLUTION_MENU = {
    "1": Resolution.SALE,
    "2": Resolution.GIFT_GIVEN,
    "3": Resolution.GIFT_RECEIVED,
    "4": Resolution.OWN_WALLET,
    "5": Resolution.EXCLUDE,
}


def load_rates(path: str) -> StaticRateProvider:
    """Loads a JSON file shaped like {"USDT": {"2026-01-05": "95.0"}} into
    a StaticRateProvider. Remember: this is a stub data source — see
    exchange_rates.py's module docstring."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    rates: dict[tuple[str, date], Decimal] = {}
    for symbol, by_date in raw.items():
        for date_str, rate in by_date.items():
            rates[(symbol, date.fromisoformat(date_str))] = Decimal(str(rate))

    return StaticRateProvider(rates)


def load_addresses(path: str) -> set[str]:
    with open(path, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Crypto tax estimator (Russia)")
    parser.add_argument("--binance-csv", action="append", default=[], help="Path to a Binance trade history CSV (repeatable)")
    parser.add_argument("--manual-wallet-json", help="Path to a manual wallet transactions JSON file")
    parser.add_argument("--own-wallets", help="Path to a text file, one wallet address per line")
    parser.add_argument("--rates", required=True, help="Path to a JSON rate lookup file")
    parser.add_argument("--output", default="report.csv", help="Where to write the output CSV")
    parser.add_argument("--with-tax", action="store_true", help="Include the Russia NDFL tax calculation")
    parser.add_argument("--interactive", action="store_true", help="Prompt in the terminal to classify unresolved transfers instead of stopping")
    parser.add_argument("--address-store", default="address_classifications.json", help="Path to the persistent address classification store")
    args = parser.parse_args()

    raw_rows: list[RawRow] = []
    for csv_path in args.binance_csv:
        raw_rows.extend(BinanceImporter().import_file(csv_path))
    if args.manual_wallet_json:
        raw_rows.extend(ManualWalletImporter().import_file(args.manual_wallet_json))

    if not raw_rows:
        print("No input transactions provided. Use --binance-csv and/or --manual-wallet-json.")
        sys.exit(1)

    rate_provider = load_rates(args.rates)
    transactions = normalize(raw_rows, rate_provider)

    own_addresses = load_addresses(args.own_wallets) if args.own_wallets else set()
    transactions, flagged = tag_wallets(transactions, own_addresses)

    store = load_store(args.address_store)
    still_flagged = apply_known_addresses(flagged, store, rate_provider)

    if still_flagged and not args.interactive:
        print(f"{len(still_flagged)} transfer(s) need manual classification before this can run:\n")
        for tx in still_flagged:
            print(f"  {tx.id} | {tx.timestamp} | {tx.asset} {tx.amount} | address: {tx.counterparty_address}")
        print(
            "\nRe-run with --interactive to classify these in the terminal, or resolve "
            "them programmatically using review_queue.resolve_transaction() — see "
            "tests/test_review_queue.py for a worked example."
        )
        sys.exit(1)

    if still_flagged and args.interactive:
        print(f"{len(still_flagged)} transfer(s) need manual classification:\n")
        for tx in still_flagged:
            print(f"\n  {tx.id} | {tx.timestamp} | {tx.asset} {tx.amount} | address: {tx.counterparty_address}")
            print("  [1] Sale  [2] Gift given  [3] Gift received  [4] My own wallet  [5] Exclude")
            choice = input("  > ").strip()

            resolution = _RESOLUTION_MENU.get(choice)
            if resolution is None:
                print(f"  Unrecognized choice '{choice}'. Stopping without saving this decision.")
                sys.exit(1)

            note = ""
            if resolution == Resolution.EXCLUDE:
                note = input("  Reason for excluding (required): ").strip()

            try:
                resolved = resolve_transaction(tx, resolution, rate_provider, note=note)
            except RateNotFoundError as e:
                print(f"  Could not price this transaction: {e}")
                print("  Add the missing rate to your rates file and re-run — nothing was saved for this address.")
                sys.exit(1)

            store.set_classification(tx.counterparty_address, resolution)

            if resolved is None:  # EXCLUDE — drop it from the pipeline entirely
                transactions.remove(tx)

        save_store(store, args.address_store)
        print(f"\nSaved classifications to {args.address_store} — recurring addresses won't need re-asking next run.")

    engine = FifoEngine(rate_provider=rate_provider)
    results = engine.process(transactions)

    tax_module = RussiaNdflModule() if args.with_tax else None
    write_report(results, args.output, tax_module)
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
