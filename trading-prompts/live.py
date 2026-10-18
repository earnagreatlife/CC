#!/usr/bin/env python3
"""Forward (paper) test of the frozen model on live daily data.

MODEL (frozen, do not tune): equal-weight ensemble of the 27 SMA/RSI/breakout
combos from walkforward.py, scaled to a 12% annual volatility target, max 1x.
Each run, after the market close:
  1. downloads full daily history (yfinance) or reads --csv,
  2. appends the model's target exposure for each new close to
     paper/signals_<TICKER>.csv (append-only, never rewritten),
  3. computes paper P&L from the LOGGED signals only (filled at next open, costs on),
  4. writes paper/REPORT_<TICKER>.md: historical expectation vs live result.

Usage:
  python3 live.py --ticker SPY
  python3 live.py --ticker SPY --csv data/SPY.csv     # offline / custom data
"""
import argparse
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import load, signals
from walkforward import grid, metrics, simulate

VOL_TARGET = 0.12
MAX_LEVERAGE = 1.0
COST_BPS = 5
MODEL_ID = "ensemble27-vt12-v1"
HERE = Path(__file__).parent


def model_target(df):
    """Target exposure (0..1) decided at each close. Uses only data up to that close."""
    combos = [cfg for _, cfg in grid() if cfg is not None]
    ens = sum(signals(df, c).astype(float) for c in combos) / len(combos)
    realized = df.close.pct_change().rolling(20).std() * np.sqrt(252)
    return (ens * (VOL_TARGET / realized).clip(upper=MAX_LEVERAGE)).fillna(0)


def fetch(ticker, csv):
    if csv:
        return load(csv)
    import yfinance as yf
    raw = yf.Ticker(ticker).history(period="max", auto_adjust=True)
    if raw.empty:
        raise SystemExit(f"No data returned for {ticker}")
    raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
    raw = raw.rename_axis("Date").reset_index()
    path = HERE / "paper" / f"{ticker}_daily.csv"
    raw[["Date", "Open", "High", "Low", "Close", "Volume"]].to_csv(path, index=False)
    return load(path)


def update_log(log_path, df, target):
    run_ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if log_path.exists():
        log = pd.read_csv(log_path, parse_dates=["date"])
        new_dates = df.index[df.index > log.date.max()]
        first_run = False
    else:
        log = pd.DataFrame(columns=["date", "close", "target", "model", "logged_at", "backfilled"])
        new_dates = df.index[-1:]  # paper trading starts at the latest close
        first_run = True
    rows = [{"date": d.date(), "close": round(df.close[d], 4), "target": round(target[d], 4),
             "model": MODEL_ID, "logged_at": run_ts,
             "backfilled": (not first_run) and d != df.index[-1]} for d in new_dates]
    if rows:
        pd.DataFrame(rows).to_csv(log_path, mode="a", header=not log_path.exists(), index=False)
    return pd.read_csv(log_path, parse_dates=["date"]), len(rows)


def fmt(m):
    return (f"| {m['cagr']:+.1%} | {m['maxdd']:.1%} | {m['sharpe']:.2f} | "
            f"{m['pos_years']:.0%} | {m['worst_year']:+.1%} |")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ticker", default="SPY")
    p.add_argument("--csv")
    a = p.parse_args()
    (HERE / "paper").mkdir(exist_ok=True)

    df = fetch(a.ticker, a.csv)
    target = model_target(df)
    log_path = HERE / "paper" / f"signals_{a.ticker}.csv"
    log, added = update_log(log_path, df, target)

    # Historical expectation: the same frozen model over all history (skip 1y warm-up)
    hist = simulate(df, target, COST_BPS)[df.index >= df.index[0] + pd.DateOffset(years=1)]
    bh_hist = simulate(df, pd.Series(1.0, index=df.index), COST_BPS).loc[hist.index]

    # Live: P&L strictly from logged signals; flat before the first logged close
    live_target = log.set_index("date").target.reindex(df.index).fillna(0)
    start = log.date.min()
    live = simulate(df, live_target, COST_BPS)[df.index > start]
    bh_live = (df.close / df.close.shift(1) - 1)[df.index > start]

    last = log.iloc[-1]
    lines = [
        f"# Paper Trading Report: {a.ticker}",
        "",
        f"Model `{MODEL_ID}` (frozen). Updated {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC.",
        "",
        f"**Next session's target exposure: {last.target:.0%}** "
        f"(decided on the {last.date.date()} close of {last.close:,.2f}; fills at the next open)",
        "",
        "## Historical expectation (backtest, same rules)",
        f"{hist.index[0].date()} → {hist.index[-1].date()}",
        "",
        "| | CAGR | Max DD | Sharpe | Years > 0 | Worst year |",
        "|---|---|---|---|---|---|",
        "| Model " + fmt(metrics(hist)),
        "| Buy & hold " + fmt(metrics(bh_hist)),
        "",
        "## Live paper result (from the logged signals only)",
        f"Started {start.date()} · {len(live)} sessions since start · {added} new signal(s) this run",
        "",
    ]
    if len(live) >= 2:
        eq, bh_eq = (1 + live).cumprod(), (1 + bh_live).cumprod()
        lines += [
            "| | Return | Max DD |",
            "|---|---|---|",
            f"| Model | {eq.iloc[-1] - 1:+.2%} | {(eq / eq.cummax() - 1).min():.2%} |",
            f"| Buy & hold | {bh_eq.iloc[-1] - 1:+.2%} | {(bh_eq / bh_eq.cummax() - 1).min():.2%} |",
            "",
            f"Average exposure: {live_target[live.index].mean():.0%}",
        ]
        if len(live) < 250:
            lines.append(f"\n_Only {len(live)} sessions so far. Under ~1 year, the live result is mostly noise._")
    else:
        lines.append("_Not enough live sessions yet. Results appear after the second close._")
    report = "\n".join(lines) + "\n"
    (HERE / "paper" / f"REPORT_{a.ticker}.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
