#!/usr/bin/env python3
"""Long-only backtester for daily OHLCV CSVs (Yahoo/Stooq export format).

Signals are computed on the close and filled at the NEXT bar's open, so there is
no lookahead. Costs are charged per side in basis points.

Usage:
  python3 backtest.py SPY.csv --strategy sma --fast 50 --slow 200
  python3 backtest.py SPY.csv --strategy rsi --rsi-buy 30 --rsi-sell 55 --split 0.7
"""
import argparse
import sys

import numpy as np
import pandas as pd


def load(path):
    df = pd.read_csv(path)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    if "adj_close" in df.columns:  # back-adjust OHLC for splits/dividends
        ratio = df["adj_close"] / df["close"]
        for c in ("open", "high", "low", "close"):
            df[c] = df[c] * ratio
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    df = df[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(df) < 50:
        sys.exit(f"Need at least 50 bars, got {len(df)}.")
    return df


def rsi(close, n=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss)


def signals(df, a):
    """Return a 0/1 'want to be long' series evaluated at each close."""
    if a.strategy == "sma":
        fast, slow = df.close.rolling(a.fast).mean(), df.close.rolling(a.slow).mean()
        return (fast > slow).astype(int).where(slow.notna(), 0)
    if a.strategy == "rsi":
        r = rsi(df.close, a.rsi_len)
        state, out = 0, []
        for v in r:
            if state == 0 and v < a.rsi_buy:
                state = 1
            elif state == 1 and v > a.rsi_sell:
                state = 0
            out.append(state)
        return pd.Series(out, index=df.index)
    if a.strategy == "breakout":
        hi = df.high.rolling(a.lookback).max().shift(1)
        lo = df.low.rolling(a.exit_lookback).min().shift(1)
        state, out = 0, []
        for c, h, l in zip(df.close, hi, lo):
            if state == 0 and c > h:
                state = 1
            elif state == 1 and c < l:
                state = 0
            out.append(state)
        return pd.Series(out, index=df.index)
    raise ValueError(a.strategy)


def run(df, sig, cost_bps):
    """Simulate next-open fills. Returns (equity curve, list of trade returns)."""
    pos = sig.shift(1).fillna(0)  # position held during bar t, decided at close t-1
    cost = cost_bps / 1e4
    equity, trades = [1.0], []
    entry = None
    for i in range(1, len(df)):
        o, c, prev_c = df.open.iloc[i], df.close.iloc[i], df.close.iloc[i - 1]
        p_now, p_prev = pos.iloc[i], pos.iloc[i - 1]
        r = 1.0
        if p_now and not p_prev:  # enter at open
            r = (c / o) * (1 - cost)
            entry = o
        elif p_prev and not p_now:  # exit at open
            r = (o / prev_c) * (1 - cost)
            trades.append(o / entry * (1 - cost) ** 2 - 1)
            entry = None
        elif p_now:
            r = c / prev_c
        equity.append(equity[-1] * r)
    if entry is not None:  # mark open trade to last close
        trades.append(df.close.iloc[-1] / entry * (1 - cost) ** 2 - 1)
    return pd.Series(equity, index=df.index), trades


def stats(eq, trades, pos):
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    dd = (eq / eq.cummax() - 1).min()
    t = np.array(trades)
    wins, losses = t[t > 0], t[t <= 0]
    pf = wins.sum() / -losses.sum() if losses.sum() < 0 else float("inf")
    cagr = eq.iloc[-1] ** (1 / years) - 1
    daily = eq.pct_change().dropna()
    sharpe = daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else 0.0
    return {
        "Total return": f"{eq.iloc[-1] - 1:+.1%}",
        "CAGR": f"{cagr:+.2%}",
        "Max drawdown": f"{dd:.1%}",
        "CAGR / MaxDD": f"{cagr / -dd:.2f}" if dd < 0 else "n/a",
        "Sharpe (daily, rf=0)": f"{sharpe:.2f}",
        "Trades": len(t),
        "Win rate": f"{len(wins) / len(t):.1%}" if len(t) else "n/a",
        "Profit factor": f"{pf:.2f}" if len(t) else "n/a",
        "Avg win / avg loss": f"{wins.mean():+.2%} / {losses.mean():+.2%}" if len(wins) and len(losses) else "n/a",
        "Exposure (time in market)": f"{pos.mean():.0%}",
    }


def report(label, df, sig, a):
    eq, trades = run(df, sig, a.cost_bps)
    s = stats(eq, trades, sig.shift(1).fillna(0))
    bh = df.close / df.close.iloc[0]
    bh_dd = (bh / bh.cummax() - 1).min()
    years = max((df.index[-1] - df.index[0]).days / 365.25, 1e-9)
    print(f"\n== {label}: {df.index[0].date()} -> {df.index[-1].date()} ({len(df)} bars) ==")
    for k, v in s.items():
        print(f"  {k:<28}{v}")
    print(f"  {'Buy & hold return / CAGR':<28}{bh.iloc[-1] - 1:+.1%} / {bh.iloc[-1] ** (1 / years) - 1:+.2%}")
    print(f"  {'Buy & hold max drawdown':<28}{bh_dd:.1%}")
    if len(trades) < 30:
        print(f"  WARNING: only {len(trades)} trades - not statistically meaningful.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv")
    p.add_argument("--strategy", choices=["sma", "rsi", "breakout"], default="sma")
    p.add_argument("--fast", type=int, default=50)
    p.add_argument("--slow", type=int, default=200)
    p.add_argument("--rsi-len", type=int, default=14)
    p.add_argument("--rsi-buy", type=float, default=30)
    p.add_argument("--rsi-sell", type=float, default=55)
    p.add_argument("--lookback", type=int, default=55, help="breakout entry: N-day high")
    p.add_argument("--exit-lookback", type=int, default=20, help="breakout exit: N-day low")
    p.add_argument("--cost-bps", type=float, default=5, help="cost per side incl. slippage")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--split", type=float, help="in-sample fraction, e.g. 0.7")
    a = p.parse_args()

    df = load(a.csv)
    sig = signals(df, a)  # indicators warm up on full history before slicing
    df, sig = df.loc[a.start:a.end], sig.loc[a.start:a.end]
    print(f"Strategy: {a.strategy} | costs {a.cost_bps} bps/side | fills at next open")
    if a.split:
        cut = int(len(df) * a.split)
        report("IN-SAMPLE", df.iloc[:cut], sig.iloc[:cut], a)
        report("OUT-OF-SAMPLE", df.iloc[cut:], sig.iloc[cut:], a)
    else:
        report("FULL PERIOD", df, sig, a)


if __name__ == "__main__":
    main()
