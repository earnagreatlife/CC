#!/usr/bin/env python3
"""Walk-forward adaptive strategy selector, the honest version of a "dynamic algo".

Each test period (default 1 year) it:
  1. scores every strategy/parameter combo in the grid on the PRIOR `--train` years only,
  2. trades the winner on the next period, which it has never seen,
  3. rolls forward and repeats.
The stitched equity curve is 100% out-of-sample. Optional volatility targeting
scales exposure to hit a target annual volatility (the most robust known way to
make returns smoother; it does not predict direction).

Fills: target computed on close t, executed at open t+1. Costs per unit traded.

Usage:
  python3 walkforward.py data/SP500_1999-2018.csv
  python3 walkforward.py data/SP500_1999-2018.csv --train 5 --vol-target 0.12
"""
import argparse
import itertools
from types import SimpleNamespace

import numpy as np
import pandas as pd

from backtest import load, signals


def grid():
    yield "buy&hold", None
    for f, s in itertools.product((20, 50, 100), (100, 150, 200)):
        if f < s:
            yield f"sma {f}/{s}", SimpleNamespace(strategy="sma", fast=f, slow=s)
    for b, s in itertools.product((25, 30, 35), (50, 55, 65)):
        yield f"rsi {b}/{s}", SimpleNamespace(strategy="rsi", rsi_len=14, rsi_buy=b, rsi_sell=s)
    for lb, ex in itertools.product((20, 55, 100), (10, 20, 50)):
        if ex < lb:
            yield f"breakout {lb}/{ex}", SimpleNamespace(strategy="breakout", lookback=lb, exit_lookback=ex)


def simulate(df, target, cost_bps):
    """Daily returns for a fractional target exposure (decided at close, filled next open)."""
    held = target.shift(1).fillna(0)        # exposure during bar t (after the open)
    overnight = target.shift(2).fillna(0)   # exposure carried through the gap into bar t
    gap = df.open / df.close.shift(1) - 1
    intraday = df.close / df.open - 1
    cost = (held - overnight).abs() * cost_bps / 1e4
    r = (1 + overnight * gap.fillna(0)) * (1 + held * intraday) * (1 - cost) - 1
    return r


def metrics(r):
    eq = (1 + r).cumprod()
    years = (r.index[-1] - r.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / years) - 1
    dd = (eq / eq.cummax() - 1).min()
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0.0
    yearly = (1 + r).groupby(r.index.year).prod() - 1
    return dict(cagr=cagr, maxdd=dd, sharpe=sharpe, vol=r.std() * np.sqrt(252),
                pos_years=(yearly > 0).mean(), worst_year=yearly.min(), yearly=yearly)


def score(r):
    m = metrics(r)
    return m["cagr"] / -m["maxdd"] if m["maxdd"] < 0 else m["cagr"]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv")
    p.add_argument("--train", type=float, default=3, help="training window, years")
    p.add_argument("--test", type=float, default=1, help="test/hold window, years")
    p.add_argument("--vol-target", type=float, help="annual vol target, e.g. 0.12")
    p.add_argument("--max-leverage", type=float, default=1.0)
    p.add_argument("--cost-bps", type=float, default=5)
    a = p.parse_args()

    df = load(a.csv)
    combos = list(grid())
    sigs = {name: (pd.Series(1, index=df.index) if cfg is None else signals(df, cfg)).astype(float)
            for name, cfg in combos}
    rets = {name: simulate(df, s, a.cost_bps) for name, s in sigs.items()}

    start = df.index[0] + pd.DateOffset(years=int(a.train * 12) // 12, months=int(a.train * 12) % 12)
    step = pd.DateOffset(months=int(a.test * 12))
    target = pd.Series(0.0, index=df.index)
    log = []
    t0 = start
    while t0 < df.index[-1]:
        t1 = t0 + step
        train = slice(t0 - pd.DateOffset(months=int(a.train * 12)), t0 - pd.Timedelta(days=1))
        best = max(rets, key=lambda n: score(rets[n].loc[train]))
        # Hand-off: the new pick's target applies from the close before t0
        window = (target.index >= t0) & (target.index < t1)
        prev = target.index[target.index < t0]
        idx = window.copy()
        if len(prev):
            idx[target.index.get_loc(prev[-1])] = True
        target[idx] = sigs[best][idx]
        log.append((t0.date(), best, score(rets[best].loc[train])))
        t0 = t1

    # Benchmark that needs no selection at all: equal-weight average of every non-B&H combo
    ensemble = sum(s for n, s in sigs.items() if n != "buy&hold") / (len(sigs) - 1)

    if a.vol_target:
        realized = df.close.pct_change().rolling(20).std() * np.sqrt(252)
        scale = (a.vol_target / realized).clip(upper=a.max_leverage).fillna(0)
        target, ensemble = target * scale, ensemble * scale

    oos = df.index >= start
    wf = simulate(df, target, a.cost_bps)[oos]
    ens = simulate(df, ensemble, a.cost_bps)[oos]
    bh = rets["buy&hold"][oos]
    sma = rets["sma 50/200"][oos]

    print(f"Walk-forward: train {a.train}y -> trade {a.test}y | {len(combos)} combos | "
          f"vol target {a.vol_target or 'off'} | costs {a.cost_bps} bps")
    print(f"Out-of-sample period: {wf.index[0].date()} -> {wf.index[-1].date()}\n")
    print("Picks (chosen using only prior data):")
    for d, n, s in log:
        print(f"  {d}  {n:<16} train score {s:5.2f}")
    print()
    rows = {"Walk-forward adaptive": metrics(wf), "Ensemble (all combos)": metrics(ens),
            "Static SMA 50/200": metrics(sma), "Buy & hold": metrics(bh)}
    print(f"{'':<24}{'CAGR':>8}{'MaxDD':>8}{'Vol':>7}{'Sharpe':>8}{'Yrs>0':>7}{'Worst yr':>10}")
    for k, m in rows.items():
        print(f"{k:<24}{m['cagr']:>+8.1%}{m['maxdd']:>8.1%}{m['vol']:>7.1%}{m['sharpe']:>8.2f}"
              f"{m['pos_years']:>7.0%}{m['worst_year']:>+10.1%}")
    print("\nCalendar-year returns:")
    yr = pd.DataFrame({k: m["yearly"] for k, m in rows.items()})
    print(yr.map(lambda v: f"{v:+.1%}").to_string())


if __name__ == "__main__":
    main()
