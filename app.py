"""
Local dashboard for the crypto tax estimator, built with Streamlit.

Run with:
    pip install streamlit
    streamlit run app.py

Everything here calls directly into the same src/ modules the CLI and
tests use — no calculation logic is reimplemented in this file. If a
number appears here, it went through the same FIFO engine, the same
fee valuation, the same tax module that the 27 tests in tests/ check.
That's deliberate: a prettier UI is worthless if it's a second,
untested code path computing your tax numbers.

Runs entirely on your machine. No data leaves it — there is no server
component beyond the local Streamlit process on localhost.

HONESTY NOTE: this file was written in a sandbox with no ability to
install or run Streamlit, so it has been checked for syntax correctness
(py_compile) but NOT actually launched and clicked through. Report any
issue you hit running it for real — see README.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import load_addresses, load_rates
from src.exchange_rates import RateNotFoundError, StaticRateProvider
from src.fifo_engine import FifoEngine, InsufficientLotsError, UnvaluedFeeError
from src.gain_loss import summarize_by_year
from src.importers.binance import BinanceImporter, MismatchedPairError
from src.importers.manual_wallet import ManualWalletImporter
from src.normalize import normalize
from src.report import _fmt
from src.review_queue import AddressClassificationStore, Resolution, apply_known_addresses, resolve_transaction
from src.tax_modules.russia_ndfl import RussiaNdflModule
from src.wallet_tagging import tag_wallets

st.set_page_config(page_title="Crypto Tax Estimator", layout="wide")


def _save_upload_to_temp(uploaded_file) -> str:
    suffix = Path(uploaded_file.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getvalue())
        return tmp.name


def _init_state() -> None:
    defaults = {
        "stage": "input",
        "store": AddressClassificationStore(),
        "transactions": None,
        "still_flagged": None,
        "rate_provider": None,
        "results": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _reset() -> None:
    for key in ["stage", "store", "transactions", "still_flagged", "rate_provider", "results"]:
        del st.session_state[key]
    _init_state()


_init_state()

st.title("Crypto tax estimator")
st.caption(
    "Estimate only, not a filing — see README.md for full assumptions and "
    "known limitations before relying on any number shown here."
)

# ---------------------------------------------------------------- INPUT ----
if st.session_state.stage == "input":
    with st.sidebar:
        st.header("Input files")
        binance_files = st.file_uploader(
            "Binance trade history CSV(s)", type="csv", accept_multiple_files=True
        )
        wallet_file = st.file_uploader("Manual wallet events JSON (optional)", type="json")
        rates_file = st.file_uploader("Rate lookup JSON", type="json")
        own_wallets_text = st.text_area(
            "Your own wallet addresses (one per line)",
            help="Transfers between these addresses are automatically treated as non-taxable.",
        )
        with_tax = st.checkbox("Calculate Russia NDFL tax", value=True)
        run = st.button("Run", type="primary")

    st.write("Upload your files in the sidebar, then click **Run**.")
    st.write(
        "No sample data is preloaded here — see the `examples/` folder in "
        "the project for files you can upload to try this without your own data."
    )

    if run:
        if not binance_files and not wallet_file:
            st.error("Upload at least one Binance CSV or a manual wallet JSON file.")
            st.stop()
        if not rates_file:
            st.error("A rate lookup JSON file is required.")
            st.stop()

        try:
            raw_rows = []
            for f in binance_files or []:
                raw_rows.extend(BinanceImporter().import_file(_save_upload_to_temp(f)))
            if wallet_file:
                raw_rows.extend(ManualWalletImporter().import_file(_save_upload_to_temp(wallet_file)))

            rate_provider = load_rates(_save_upload_to_temp(rates_file))
            transactions = normalize(raw_rows, rate_provider)

            own_addresses = {line.strip() for line in own_wallets_text.splitlines() if line.strip()}
            transactions, flagged = tag_wallets(transactions, own_addresses)
            still_flagged = apply_known_addresses(flagged, st.session_state.store, rate_provider)

            st.session_state.transactions = transactions
            st.session_state.rate_provider = rate_provider
            st.session_state.still_flagged = still_flagged
            st.session_state.with_tax = with_tax
            st.session_state.stage = "review" if still_flagged else "compute"
            st.rerun()

        except MismatchedPairError as e:
            st.error(f"CSV parsing issue: {e}")
        except RateNotFoundError as e:
            st.error(f"Missing rate data: {e}")
        except Exception as e:
            st.error(f"Could not process input: {e}")

# --------------------------------------------------------------- REVIEW ----
elif st.session_state.stage == "review":
    st.subheader(f"{len(st.session_state.still_flagged)} transfer(s) need classification")
    st.write(
        "These addresses aren't on your own-wallet list and haven't been "
        "classified before. Nothing here is guessed — classify each one "
        "below."
    )

    resolutions = {}
    notes = {}
    for tx in st.session_state.still_flagged:
        st.markdown(f"**{tx.id}** — {tx.timestamp} — {tx.amount} {tx.asset} — `{tx.counterparty_address}`")
        col1, col2 = st.columns([2, 3])
        with col1:
            choice = st.selectbox(
                "Classify as",
                options=["Sale", "Gift given", "Gift received", "My own wallet", "Exclude"],
                key=f"choice_{tx.id}",
            )
        resolutions[tx.id] = {
            "Sale": Resolution.SALE,
            "Gift given": Resolution.GIFT_GIVEN,
            "Gift received": Resolution.GIFT_RECEIVED,
            "My own wallet": Resolution.OWN_WALLET,
            "Exclude": Resolution.EXCLUDE,
        }[choice]
        if choice == "Exclude":
            with col2:
                notes[tx.id] = st.text_input("Reason for excluding (required)", key=f"note_{tx.id}")

    if st.button("Apply classifications", type="primary"):
        transactions = st.session_state.transactions
        rate_provider = st.session_state.rate_provider
        errors = []

        for tx in st.session_state.still_flagged:
            resolution = resolutions[tx.id]
            note = notes.get(tx.id, "")
            if resolution == Resolution.EXCLUDE and not note.strip():
                errors.append(f"{tx.id}: exclude reason is required")
                continue
            try:
                resolved = resolve_transaction(tx, resolution, rate_provider, note=note)
            except RateNotFoundError as e:
                errors.append(f"{tx.id}: {e}")
                continue
            st.session_state.store.set_classification(tx.counterparty_address, resolution)
            if resolved is None:
                transactions.remove(tx)

        if errors:
            for e in errors:
                st.error(e)
        else:
            st.session_state.stage = "compute"
            st.rerun()

    if st.button("Start over"):
        _reset()
        st.rerun()

# -------------------------------------------------------------- COMPUTE ----
elif st.session_state.stage == "compute":
    try:
        engine = FifoEngine(rate_provider=st.session_state.rate_provider)
        results = engine.process(st.session_state.transactions)
        st.session_state.results = results
        st.session_state.stage = "results"
        st.rerun()
    except InsufficientLotsError as e:
        st.error(f"Missing acquisition history: {e}")
        if st.button("Start over"):
            _reset()
            st.rerun()
    except UnvaluedFeeError as e:
        st.error(f"Fee valuation issue: {e}")
        if st.button("Start over"):
            _reset()
            st.rerun()

# -------------------------------------------------------------- RESULTS ----
elif st.session_state.stage == "results":
    results = st.session_state.results
    gains_by_year = summarize_by_year(results)

    st.subheader("Summary")
    if st.session_state.with_tax:
        tax_by_year = RussiaNdflModule().compute_tax_by_year(gains_by_year)
        cols = st.columns(len(gains_by_year) or 1)
        for col, year in zip(cols, sorted(gains_by_year)):
            with col:
                st.metric(f"{year} net gain/loss", f"₽{_fmt(gains_by_year[year])}")
                st.metric(f"{year} tax owed (RU)", f"₽{_fmt(tax_by_year[year])}")
    else:
        cols = st.columns(len(gains_by_year) or 1)
        for col, year in zip(cols, sorted(gains_by_year)):
            with col:
                st.metric(f"{year} net gain/loss", f"₽{_fmt(gains_by_year[year])}")

    if len(gains_by_year) > 1:
        st.bar_chart({str(y): float(g) for y, g in gains_by_year.items()})

    st.subheader("Every disposal")
    table_rows = [
        {
            "date": r.disposed_at.date().isoformat(),
            "asset": r.asset,
            "amount": _fmt(r.amount_disposed),
            "proceeds_rub": _fmt(r.proceeds_rub),
            "cost_basis_rub": _fmt(r.cost_basis_rub),
            "gain_loss_rub": _fmt(r.gain_loss_rub),
        }
        for r in sorted(results, key=lambda r: r.disposed_at)
    ]
    st.dataframe(table_rows, use_container_width=True)

    csv_lines = ["date,asset,amount,proceeds_rub,cost_basis_rub,gain_loss_rub"]
    for row in table_rows:
        csv_lines.append(",".join(row.values()))
    st.download_button(
        "Download report CSV",
        data="\n".join(csv_lines),
        file_name="report.csv",
        mime="text/csv",
    )

    if st.button("Start over"):
        _reset()
        st.rerun()
