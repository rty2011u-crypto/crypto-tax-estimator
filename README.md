# Crypto Tax Estimator (Russia)

## What this tool is

This is an open-source estimator for crypto capital gains and Russian NDFL
liability under Federal Law No. 418-FZ. It is a personal project, built
and shared for free, with no warranty of any kind (MIT License).

## What this tool is NOT

- It is not tax advice, and it does not replace an accountant.
- It is not a filing tool — it does not submit anything to the FNS.
- It has not been reviewed by a tax professional. Use it to get an
  estimate, then verify the result before relying on it for an actual
  3-NDFL filing.

## Known limitations — read before trusting the output

**1. The CBR and CoinGecko rate providers are code-complete but NOT
live-tested.** They were built and verified in an environment with no
network access — their response-parsing logic is tested against canned
sample data (see `tests/test_rate_provider_parsing.py`), but the actual
HTTP calls have never been exercised against a live response. Run one
real lookup for a date/value you can check by hand before trusting either
for a real filing.

**2. DeFi protocols, liquidity pools, and staking rewards are not
supported at all.**

## How swaps are accounted for

Every trade quoted in RUB is a single taxable event (rubles are money,
not property). Every trade quoted in anything else — a stablecoin
(USDT, USDC, BUSD) or another crypto asset (e.g. ETHBTC) — is treated as
a swap: a disposal of what you gave up and an acquisition of what you
received, because Russian guidance treats switching between digital
currencies, including into/out of a stablecoin, as a taxable event on
both sides. Each leg is priced at ITS OWN independent market rate on
that date, not derived from the other leg's trade price — the same
principle used for mining income and gifts. This means a stablecoin you
hold has its own FIFO cost-basis history, same as any other asset; if
you've never actually acquired it through a tracked transaction (e.g.
you started with USDT already in your account before you began
recording), the engine will correctly refuse to process a disposal of it
via `InsufficientLotsError` rather than guess a cost basis of zero.

## Assumptions this tool makes (read before trusting the output)

- **Cost-basis method: FIFO.** Oldest purchase is matched to each sale,
  in order, per asset.
- **Gift-received valuation:** assumed to be market value at the date
  received. This is a reasonable reading of general principles, not a
  confirmed rule for individuals — verify against current FNS guidance.
- **Fee valuation:** a fee paid in the same asset as the trade uses that
  trade's price. A fee paid in a different asset (e.g. a BNB fee on a BTC
  trade) is valued at that fee asset's own market rate on the transaction
  date.
- **Exchange rate sources:** `CbrRateProvider` (Central Bank of Russia
  daily feed) for fiat, `CoinGeckoRateProvider` for crypto asset market
  prices — see limitation #1 above. On weekends/holidays with no
  published rate, the most recent prior published rate is used (looked
  back up to 7 days by default).
- **Wallet transfers are never auto-classified as taxable or non-taxable
  by guessing.** A transfer only clears automatically if its address is
  on your declared "own wallets" list or has a stored prior
  classification; anything else stops the run (or prompts you, with
  `--interactive`) rather than assuming.
- **Jurisdiction: Russia only**, under the rules in effect as of [date].
  Tax law changes; this tool does not automatically stay current.

## How it works (brief)

1. Import exchange CSVs and manually-declared wallet transactions.
2. Normalize everything into one transaction format, converting prices to
   RUB via a rate provider.
3. Tag wallet-to-wallet transfers: known-own-wallet = non-taxable,
   everything else is flagged for manual classification (never assumed).
   Addresses seen and classified before are remembered across runs.
4. Track cost basis per asset using a FIFO lot queue.
5. Compute gain/loss per disposal event.
6. Optionally apply the Russian NDFL bracket calculation (13% up to
   ₽2.4M profit/year, 15% above that) on top of the gain/loss figures.

## Running it

```
python3 main.py \
  --binance-csv path/to/export.csv \
  --manual-wallet-json path/to/wallet_events.json \
  --own-wallets path/to/my_addresses.txt \
  --rates path/to/rates.json \
  --with-tax \
  --interactive \
  --output report.csv
```

`--interactive` prompts in the terminal for any wallet transfer that
can't be auto-cleared, and remembers each decision in
`--address-store` (default `address_classifications.json`) so the same
address doesn't need re-classifying on a future run. Omit
`--interactive` to have the run stop and list unresolved transfers
instead — useful for scripting, where an unattended prompt isn't safe.

See `examples/` for sample input files in the expected format.

## If you find a bug in the calculation logic

Please open an issue. Given this directly affects how people estimate
money owed, calculation bugs are treated as the highest priority.
