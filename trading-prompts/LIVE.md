# Live Forward Test

The only honest way to find out how a model does on live data is to **freeze it, log every
decision before the outcome is known, and wait**. This folder does that automatically.

## The model (frozen: `ensemble27-vt12-v1`)
- Averages the long/flat signals from 27 SMA, RSI and breakout rules (no parameter picking).
- Scales exposure to a 12% annual volatility target, capped at 100%. No leverage, no shorts.
- Decides at each close and fills at the next open, with 5 bps costs.
- Chosen because it was the most **consistent** system out of sample (see `RESULTS.md`). It is
  not the highest-return one. Expect roughly half of buy & hold's return with about a quarter of the drawdown.

## How it runs
`.github/workflows/paper-trade.yml` runs every weekday at 22:15 UTC on GitHub's servers:
1. downloads the full SPY and QQQ daily history from Yahoo Finance,
2. appends the model's next-session exposure to `paper/signals_<TICKER>.csv`,
3. computes paper P&L **only from those logged signals**,
4. writes `paper/REPORT_<TICKER>.md` with the historical expectation next to the live result, and commits it.

The signal log is append-only and timestamped (`logged_at`). Rows filled in after a missed
run are flagged `backfilled=True`. Git history is the proof that no decision was edited after the fact.

Run it by hand: `python3 live.py --ticker SPY` (needs `pip install pandas numpy yfinance`).

## Verified
- A day-by-day replay on real S&P 500 data (2018-H2, including skipped runs) logged signals that match
  the full-history computation exactly (max difference 0.0), so the model has no lookahead.
- Live data download via GitHub Actions is verified on the first workflow run.

## How to read the results
- Under about 1 year of live data, the result is mostly noise. Judge it after 12+ months.
- What counts as **working**: live max drawdown and volatility close to the historical row, and a
  much smaller drawdown than buy & hold in a sell-off. Lagging buy & hold in a strong bull market is expected.
- **Do not change the rules because of live results.** Changing them restarts the clock. Any new model
  gets a new `MODEL_ID` and its own fresh forward test.
- Paper results ignore taxes, partial fills and dividends paid while out of the market. Real money comes after 12 months of paper trading, at small size.
