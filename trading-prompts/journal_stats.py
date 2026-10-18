#!/usr/bin/env python3
"""Exact stats for a trading journal CSV, to feed the Journal Analyzer prompt.

Columns: date,ticker,side,entry,exit,shares[,stop,setup,notes]
  side = long|short. stop (optional) enables R-multiples.

Usage: python3 journal_stats.py my_trades.csv
"""
import sys

import pandas as pd


def main(path):
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df.index += 1
    sign = df["side"].str.lower().map({"long": 1, "short": -1})
    if sign.isna().any():
        sys.exit("side must be 'long' or 'short' on every row")
    df["pnl"] = (df["exit"] - df["entry"]) * df["shares"] * sign
    has_r = "stop" in df and df["stop"].notna().any()
    if has_r:
        risk = (df["entry"] - df["stop"]).abs() * df["shares"]
        df["R"] = (df["pnl"] / risk).round(2)
        df["risk_$"] = risk.round(2)
    if "setup" not in df:
        df["setup"] = "n/a"

    w, l = df[df.pnl > 0], df[df.pnl <= 0]
    eq = df.pnl.cumsum()
    print(f"Trades: {len(df)}  |  {df.date.min().date()} -> {df.date.max().date()}")
    print(f"Net P&L: {df.pnl.sum():,.2f}  |  Win rate: {len(w) / len(df):.0%}")
    print(f"Avg win: {w.pnl.mean():,.2f}  |  Avg loss: {l.pnl.mean():,.2f}")
    pf = w.pnl.sum() / -l.pnl.sum() if l.pnl.sum() < 0 else float("inf")
    print(f"Profit factor: {pf:.2f}  |  Expectancy/trade: {df.pnl.mean():,.2f}")
    print(f"Max drawdown ($, closed trades): {(eq - eq.cummax()).min():,.2f}")
    print(f"Largest win: #{df.pnl.idxmax()} {df.pnl.max():,.2f}  |  Largest loss: #{df.pnl.idxmin()} {df.pnl.min():,.2f}")

    # Losing streaks and what happened right after a loss (revenge-trade check)
    streak = mx = 0
    for p in df.pnl:
        streak = streak + 1 if p <= 0 else 0
        mx = max(mx, streak)
    after_loss = df.pnl[df.pnl.shift(1) <= 0]
    print(f"Longest losing streak: {mx}  |  Avg P&L on trade after a loss: {after_loss.mean():,.2f} (n={len(after_loss)})")

    if has_r:
        print(f"Avg R: {df.R.mean():+.2f}  |  Avg win R: {df.R[df.R > 0].mean():+.2f}  |  Avg loss R: {df.R[df.R <= 0].mean():+.2f}")
        big = df[df.R < -1.1]
        print(f"Losses worse than -1.1R (stop moved/ignored?): {list(big.index) or 'none'}")
        print(f"Risk per trade ($): min {df['risk_$'].min():,.0f} / median {df['risk_$'].median():,.0f} / max {df['risk_$'].max():,.0f}")

    print("\nBy setup:")
    g = df.groupby("setup").pnl
    print(pd.DataFrame({"n": g.size(), "net": g.sum().round(2), "win%": (g.apply(lambda s: (s > 0).mean()) * 100).round(0)})
          .sort_values("net").to_string())
    print("\nBy side:")
    print(df.groupby("side").pnl.agg(["size", "sum"]).round(2).to_string())

    cols = ["date", "ticker", "side", "setup", "pnl"] + (["R"] if has_r else []) + (["notes"] if "notes" in df else [])
    print("\nTrades:")
    print(df[cols].assign(date=df.date.dt.date, pnl=df.pnl.round(2)).to_string())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
