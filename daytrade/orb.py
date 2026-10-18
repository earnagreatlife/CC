"""5-minute Opening Range Breakout on stocks in play. Shared by backtest_orb.py and bot.py,
so the backtest tests the exact logic that trades.

Hypothesis source: Zarattini, Barbon & Aziz (2023-24), ORB day-trading papers (SSRN).
Rules (frozen as MODEL_ID; change anything -> new id, new forward test):
  * Universe: liquid US stocks. Each day rank by relative volume of the 9:30-9:35 bar
    vs its prior-14-day average. Need price >= $5, ATR(14) >= $0.50, RelVol >= 1.0.
  * Take the top N. Green first bar -> buy-stop at its high. Red -> sell-stop at its low.
    Doji -> skip.
  * Stop = 10% of ATR(14) from entry. Risk 0.5% of equity per trade, cap position at
    equity / N. Entries only until 10:30 ET. Flat at 15:55 ET. No targets, no overnight.
"""
from dataclasses import dataclass, field
import math

import pandas as pd

MODEL_ID = "orb5-relvol-v1"

UNIVERSE = (
    "AAPL MSFT NVDA AMZN META GOOGL TSLA AMD NFLX AVGO COIN MSTR PLTR SMCI MU INTC BA DIS "
    "JPM BAC XOM CVX UBER SHOP PYPL CRM ORCL ADBE QCOM ARM SNOW ROKU RIVN SOFI NIO BABA "
    "F GM WMT COST LLY UNH MRNA PFE DKNG ABNB HOOD RBLX MARA RIOT"
).split()


@dataclass
class Params:
    universe: list = field(default_factory=lambda: list(UNIVERSE))
    top_n: int = 5
    min_price: float = 5.0
    min_atr: float = 0.50
    min_relvol: float = 1.0
    stop_atr_frac: float = 0.10
    risk_pct: float = 0.005
    entry_deadline: str = "10:30"
    exit_time: str = "15:55"
    daily_loss_limit: float = 0.02
    lookback: int = 14


def daily_stats(daily, opening, p):
    """daily: symbol,date,o,h,l,c ; opening: symbol,date,v (9:30 5-min bar volume).
    Returns symbol,date -> atr, avg_open_vol using ONLY prior days (shifted)."""
    out = []
    for sym, d in daily.groupby("symbol"):
        d = d.sort_values("date").set_index("date")
        pc = d.c.shift(1)
        tr = pd.concat([d.h - d.l, (d.h - pc).abs(), (d.l - pc).abs()], axis=1).max(axis=1)
        atr = tr.rolling(p.lookback).mean().shift(1)
        ov = opening[opening.symbol == sym].set_index("date").v.reindex(d.index)
        avg_ov = ov.rolling(p.lookback, min_periods=p.lookback // 2).mean().shift(1)
        out.append(pd.DataFrame({"symbol": sym, "atr": atr, "avg_open_vol": avg_ov}, index=d.index))
    return pd.concat(out).reset_index().rename(columns={"index": "date"})


def select(first_bars, stats, p):
    """first_bars: symbol -> dict(o,h,l,c,v) for 9:30-9:35. stats: symbol -> dict(atr, avg_open_vol).
    Returns ranked plans: dict(symbol, side, trigger, stop_dist, relvol, atr)."""
    plans = []
    for sym, b in first_bars.items():
        st = stats.get(sym)
        if not st or not (st["atr"] > 0) or not (st["avg_open_vol"] > 0):
            continue
        relvol = b["v"] / st["avg_open_vol"]
        if b["c"] < p.min_price or st["atr"] < p.min_atr or relvol < p.min_relvol or b["c"] == b["o"]:
            continue
        side = "buy" if b["c"] > b["o"] else "sell"
        plans.append(dict(symbol=sym, side=side, trigger=b["h"] if side == "buy" else b["l"],
                          stop_dist=round(max(p.stop_atr_frac * st["atr"], 0.01), 2),
                          relvol=round(relvol, 2), atr=round(st["atr"], 2)))
    return sorted(plans, key=lambda x: -x["relvol"])[: p.top_n]


def shares(plan, price, equity, p):
    by_risk = equity * p.risk_pct / plan["stop_dist"]
    by_cap = equity / p.top_n / price
    return max(int(math.floor(min(by_risk, by_cap))), 0)


def stats_today(daily, opening, p):
    """Live equivalent of daily_stats() for today: uses only completed prior sessions."""
    out = {}
    for sym, d in daily.groupby("symbol"):
        d = d.sort_values("date")
        pc = d.c.shift(1)
        tr = pd.concat([d.h - d.l, (d.h - pc).abs(), (d.l - pc).abs()], axis=1).max(axis=1)
        ov = opening[opening.symbol == sym].sort_values("date").v.tail(p.lookback)
        if len(tr.dropna()) >= p.lookback and len(ov) >= p.lookback // 2:
            out[sym] = dict(atr=tr.tail(p.lookback).mean(), avg_open_vol=ov.mean())
    return out
