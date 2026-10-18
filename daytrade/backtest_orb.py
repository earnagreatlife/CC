#!/usr/bin/env python3
"""Backtest orb.py on REAL Alpaca 5-minute bars. Uses the same select()/shares() as the live bot.

Conservative fills: entry at max(trigger, bar open) + slippage. If a bar touches both the
entry and the stop, it counts as a loss. Gaps through the stop fill at the bar open. The
daily loss limit closes everything at the bar where realized P&L crosses it.

Usage (needs ALPACA_KEY / ALPACA_SECRET):
  python3 backtest_orb.py --years 2
"""
import argparse
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from alpaca import Alpaca
import orb

HERE = Path(__file__).parent
T930, T935 = dt.time(9, 30), dt.time(9, 35)


def fetch(api, symbols, start, end, feed):
    daily, intraday = [], []
    for i in range(0, len(symbols), 10):
        chunk = symbols[i:i + 10]
        print(f"  fetching {chunk[0]}..{chunk[-1]}", flush=True)
        daily.append(api.bars(chunk, "1Day", start, end, feed=feed))
        m5 = api.bars(chunk, "5Min", start, end, feed=feed)
        tt = m5.t.dt.time
        intraday.append(m5[(tt >= T930) & (tt < dt.time(16, 0))])
    daily = pd.concat(daily)
    daily["date"] = daily.t.dt.date
    intraday = pd.concat(intraday)
    intraday["date"] = intraday.t.dt.date
    return daily, intraday


def sim_trade(plan, bars, n, slip, p):
    """bars: one symbol's 5-min bars after 9:35, time-ordered. Returns trade dict or None."""
    deadline = dt.time.fromisoformat(p.entry_deadline)
    last_start = (dt.datetime.combine(dt.date.today(), dt.time.fromisoformat(p.exit_time))
                  - dt.timedelta(minutes=5)).time()
    long = plan["side"] == "buy"
    sgn = 1 if long else -1
    entry = None
    for i, b in enumerate(bars.itertuples()):
        bt = b.t.time()
        if entry is None:
            if bt >= deadline:
                return None
            hit = b.h >= plan["trigger"] if long else b.l <= plan["trigger"]
            if not hit:
                continue
            fill = (max(plan["trigger"], b.o) if long else min(plan["trigger"], b.o)) + sgn * slip
            stop = fill - sgn * plan["stop_dist"]
            entry = dict(symbol=plan["symbol"], side="long" if long else "short", entry=fill, stop=stop,
                         shares=n, entry_t=b.t, relvol=plan["relvol"], path=bars.iloc[i:])
            if (b.l <= stop) if long else (b.h >= stop):  # same-bar stop: assume loss
                return {**entry, "exit": stop - sgn * slip, "exit_t": b.t}
            continue
        gapped = (b.o <= stop) if long else (b.o >= stop)
        if gapped:
            return {**entry, "exit": b.o - sgn * slip, "exit_t": b.t}
        if (b.l <= stop) if long else (b.h >= stop):
            return {**entry, "exit": stop - sgn * slip, "exit_t": b.t}
        if bt >= last_start:
            return {**entry, "exit": b.c - sgn * slip, "exit_t": b.t}
    if entry is not None:  # data ended early: exit at last close
        return {**entry, "exit": bars.c.iloc[-1] - sgn * slip, "exit_t": bars.t.iloc[-1]}
    return None


def run(daily, intraday, p, slip, start_equity=100_000):
    opening = intraday[intraday.t.dt.time == T930][["symbol", "date", "o", "h", "l", "c", "v"]]
    stats = orb.daily_stats(daily[["symbol", "date", "o", "h", "l", "c"]], opening[["symbol", "date", "v"]], p)
    stats = stats.set_index(["date", "symbol"])
    by_day = intraday[intraday.t.dt.time >= T935].groupby("date")
    equity, eq_rows, trades = start_equity, [], []
    for date, first in opening.groupby("date"):
        fb = {r.symbol: dict(o=r.o, h=r.h, l=r.l, c=r.c, v=r.v) for r in first.itertuples()}
        st = {s: stats.loc[(date, s)].to_dict() for s in fb if (date, s) in stats.index}
        plans = orb.select(fb, st, p)
        day_bars = by_day.get_group(date) if date in by_day.groups else None
        day_trades = []
        if day_bars is not None:
            for pl in plans:
                n = orb.shares(pl, pl["trigger"], equity, p)
                sb = day_bars[day_bars.symbol == pl["symbol"]].sort_values("t")
                if n and len(sb):
                    t = sim_trade(pl, sb, n, slip, p)
                    if t:
                        day_trades.append(t)
        # Daily loss limit: walk exits in time order; once realized P&L <= -limit, flatten the rest
        day_trades.sort(key=lambda t: t["exit_t"])
        realized, cut_t = 0.0, None
        for t in day_trades:
            sgn = 1 if t["side"] == "long" else -1
            if cut_t is not None and t["exit_t"] > cut_t:
                if t["entry_t"] > cut_t:
                    t["skip"] = True
                    continue
                bar = t["path"][t["path"].t <= cut_t].iloc[-1]
                t["exit"], t["exit_t"] = bar.c - sgn * slip, cut_t
            t["pnl"] = (t["exit"] - t["entry"]) * t["shares"] * sgn
            realized += t["pnl"]
            if cut_t is None and realized <= -p.daily_loss_limit * equity:
                cut_t = t["exit_t"]
        done = [t for t in day_trades if not t.get("skip")]
        for t in done:
            t["date"], t["R"] = date, t["pnl"] / (abs(t["entry"] - t["stop"]) * t["shares"])
            t.pop("path")
        trades += done
        equity += sum(t["pnl"] for t in done)
        eq_rows.append((pd.Timestamp(date), equity))
    eq = pd.Series(dict(eq_rows)).sort_index()
    return eq, pd.DataFrame(trades)


def summarize(eq, tr, spy, label):
    r = eq.pct_change().fillna(eq.iloc[0] / 100_000 - 1)
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    dd = (eq / eq.cummax() - 1).min()
    out = {"label": label, "days": len(eq), "trades": len(tr),
           "total": eq.iloc[-1] / 100_000 - 1, "cagr": (eq.iloc[-1] / 100_000) ** (1 / years) - 1,
           "maxdd": dd, "sharpe": r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0}
    if len(tr):
        w, l = tr[tr.pnl > 0], tr[tr.pnl <= 0]
        out |= {"win": len(w) / len(tr), "avgR": tr.R.mean(),
                "pf": w.pnl.sum() / -l.pnl.sum() if len(l) and l.pnl.sum() < 0 else float("inf")}
    spy = spy.loc[eq.index[0]:eq.index[-1]]
    out["spy"] = spy.iloc[-1] / spy.iloc[0] - 1 if len(spy) > 1 else float("nan")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=float, default=2)
    ap.add_argument("--feed", default="sip", help="sip (all exchanges) or iex")
    ap.add_argument("--out", default=str(HERE / "results"))
    a = ap.parse_args()
    p = orb.Params()
    api = Alpaca()
    end = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    start = (dt.date.today() - dt.timedelta(days=int(a.years * 365) + 40)).isoformat()
    print(f"Fetching real {a.feed} bars {start} -> {end} for {len(p.universe)} symbols + SPY")
    daily, intraday = fetch(api, p.universe, start, end, a.feed)
    spy = api.bars(["SPY"], "1Day", start, end, feed=a.feed)
    spy = spy.set_index(spy.t.dt.tz_localize(None).dt.normalize()).c
    print(f"  {len(intraday):,} intraday bars, {intraday.date.nunique()} sessions")

    rows, trades = [], None
    for slip in (0.01, 0.03):
        eq, tr = run(daily, intraday, p, slip)
        tr = tr[tr.date >= eq.index[0].date() + dt.timedelta(days=30)] if len(tr) else tr  # warm-up
        eq = eq[eq.index >= eq.index[0] + pd.Timedelta(days=30)]
        rows.append(summarize(eq, tr, spy, f"slippage {slip * 100:.0f}c/share/side"))
        if slip == 0.01:
            trades, eq1 = tr, eq

    Path(a.out).mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().isoformat()
    j = trades.assign(ticker=trades.symbol, setup=orb.MODEL_ID,
                      notes=trades.relvol.map(lambda v: f"relvol {v}"))
    j[["date", "ticker", "side", "entry", "exit", "shares", "stop", "setup", "notes"]].round(4) \
        .to_csv(f"{a.out}/trades_{stamp}.csv", index=False)

    yearly = eq1.groupby(eq1.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
    lines = [f"# ORB Backtest: Real Data ({orb.MODEL_ID})", "",
             f"Run {stamp}. {a.feed.upper()} 5-min bars, {eq1.index[0].date()} → {eq1.index[-1].date()}, "
             f"{len(p.universe)} symbols, $100k start, 0.5% risk/trade, top {p.top_n}/day.", "",
             "| Costs | Trades | Win % | Avg R | Profit factor | Total | CAGR | Max DD | Sharpe | SPY B&H |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for o in rows:
        lines.append(f"| {o['label']} | {o['trades']} | {o.get('win', 0):.0%} | {o.get('avgR', 0):+.3f} | "
                     f"{o.get('pf', 0):.2f} | {o['total']:+.1%} | {o['cagr']:+.1%} | {o['maxdd']:.1%} | "
                     f"{o['sharpe']:.2f} | {o['spy']:+.1%} |")
    lines += ["", "**By side (1c):** " + ", ".join(
                  f"{s}: {len(g)} trades, avg R {g.R.mean():+.3f}" for s, g in trades.groupby("side")),
              "", "**By year (1c):** " + ", ".join(f"{y}: {v:+.1%}" for y, v in yearly.items()), "",
              "Caveats: the universe was picked today (survivorship bias). Slippage on fast opening moves can "
              "exceed 3c. If the result only holds at 1c, assume it fails live."]
    report = "\n".join(lines) + "\n"
    Path(f"{a.out}/BACKTEST.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
