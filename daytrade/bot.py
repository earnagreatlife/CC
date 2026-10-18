#!/usr/bin/env python3
"""Live ORB bot on Alpaca. PAPER account unless ALPACA_LIVE=I_ACCEPT_REAL_MONEY_RISK.

  python3 bot.py open    # run before 9:30 ET: plans at 9:35, enters on triggers until 10:30
  python3 bot.py close   # run before 15:55 ET: flattens everything, writes the journal
  python3 bot.py flatten # emergency: close all positions and orders now

Every stop-loss sits at the broker as part of an OTO order, so a crashed bot still has
its stops. A file named KILL in this folder stops the bot from trading.
"""
import datetime as dt
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from alpaca import Alpaca
import orb

ET = ZoneInfo("America/New_York")
HERE = Path(__file__).parent
JOURNAL = HERE / "journal"
FEED = "iex"  # free real-time feed; set to "sip" with a paid Alpaca data plan
POLL_SECONDS = 10


def now():
    return dt.datetime.now(ET)


def at(t):
    return dt.datetime.combine(now().date(), dt.time.fromisoformat(t), tzinfo=ET)


def log(msg):
    line = f"{now():%Y-%m-%d %H:%M:%S} ET  {msg}"
    print(line, flush=True)
    JOURNAL.mkdir(exist_ok=True)
    with open(JOURNAL / f"log_{now():%Y-%m-%d}.txt", "a") as f:
        f.write(line + "\n")


def wait_until(t):
    while (s := (t - now()).total_seconds()) > 0:
        time.sleep(min(s, 30))


def trading_day(api):
    c = api.clock()
    next_open = pd.Timestamp(c["next_open"]).tz_convert(ET)
    return c["is_open"] or next_open.date() == now().date()


def open_session(api, p):
    if (HERE / "KILL").exists():
        return log("KILL file present: not trading.")
    if not trading_day(api):
        return log("Market closed today.")
    if now() >= at("09:34"):
        return log("Started after 09:34 ET (scheduler delay or duplicate run): not trading today.")
    log(f"Model {orb.MODEL_ID} | {'LIVE MONEY' if api.live else 'PAPER'} account | feed {FEED}")

    # 1. Leftovers from a missed flatten: close them at the open
    if api.positions():
        wait_until(at("09:30:05"))
        log(f"Closing leftover positions: {[x['symbol'] for x in api.positions()]}")
        api.close_all()

    # 2. Prior-day stats (completed sessions only)
    start = (now().date() - dt.timedelta(days=45)).isoformat()
    today0 = at("00:00").isoformat()
    daily = api.bars(p.universe, "1Day", start, today0, feed="sip")  # prices: consolidated history
    daily["date"] = daily.t.dt.date
    m5 = api.bars(p.universe, "5Min", start, today0, feed=FEED)
    opening = m5[m5.t.dt.time == dt.time(9, 30)].assign(date=lambda d: d.t.dt.date)
    stats = orb.stats_today(daily, opening, p)
    log(f"Stats ready for {len(stats)}/{len(p.universe)} symbols. Waiting for the 9:35 bar.")

    # 3. Opening range bar
    wait_until(at("09:35:03"))
    for _ in range(12):
        fb5 = api.bars(p.universe, "5Min", at("09:30").isoformat(), at("09:35").isoformat(), feed=FEED)
        if len(fb5) >= 0.8 * len(stats):
            break
        time.sleep(5)
    fb = {r.symbol: dict(o=r.o, h=r.h, l=r.l, c=r.c, v=r.v) for r in fb5.itertuples()}
    plans = orb.select(fb, stats, p)
    acct = api.account()
    equity, last_equity = float(acct["equity"]), float(acct["last_equity"])
    if not plans:
        return log("No stocks in play passed the filters. No trades today.")
    for pl in plans:
        log(f"PLAN {pl['symbol']:<5} {pl['side']:<4} trigger {pl['trigger']:.2f} stop_dist {pl['stop_dist']:.2f} "
            f"relvol {pl['relvol']:.1f} atr {pl['atr']:.2f}")

    # 4. Trigger loop
    pending = {pl["symbol"]: pl for pl in plans}
    for sym, pl in list(pending.items()):
        if pl["side"] == "sell":
            a = api.asset(sym)
            if not (a.get("shortable") and a.get("easy_to_borrow")):
                log(f"SKIP {sym}: not easy to borrow for a short")
                pending.pop(sym)
    while pending and now() < at(p.entry_deadline):
        if (HERE / "KILL").exists():
            log("KILL file detected: stopping entries.")
            break
        eq_now = float(api.account()["equity"])
        if eq_now <= last_equity * (1 - p.daily_loss_limit):
            log(f"DAILY LOSS LIMIT hit (equity {eq_now:,.0f} vs {last_equity:,.0f}): flattening, done for today.")
            api.close_all()
            return
        prices = api.latest_trades(list(pending), feed=FEED)
        for sym, px in prices.items():
            pl = pending[sym]
            crossed = px >= pl["trigger"] if pl["side"] == "buy" else px <= pl["trigger"]
            if not crossed:
                continue
            pending.pop(sym)
            n = orb.shares(pl, px, equity, p)
            stop = round(px - pl["stop_dist"] if pl["side"] == "buy" else px + pl["stop_dist"], 2)
            if n < 1:
                log(f"SKIP {sym}: size rounds to 0 shares")
                continue
            try:
                o = api.submit(symbol=sym, qty=str(n), side=pl["side"], type="market", time_in_force="day",
                               order_class="oto", stop_loss={"stop_price": f"{stop:.2f}"},
                               client_order_id=f"orb-{now():%Y%m%d}-{sym}")
                log(f"ENTRY {sym} {pl['side']} {n} @ ~{px:.2f}, stop {stop:.2f} "
                    f"(risk ~${n * pl['stop_dist']:,.0f}) order {o['id'][:8]}")
            except RuntimeError as e:
                log(f"ORDER REJECTED {sym}: {e}")
        time.sleep(POLL_SECONDS)
    for sym in pending:
        log(f"NO TRIGGER {sym} by {p.entry_deadline}: cancelled")
    log("Entry window closed. Stops are held at the broker; the close job flattens at 15:55 ET.")


def fill_price(o):
    return float(o["filled_avg_price"]) if o.get("filled_avg_price") else None


def close_session(api, p):
    if not trading_day(api):
        return log("Market closed today.")
    wait_until(at(p.exit_time))
    if not api.clock()["is_open"]:
        log("Market already closed: leftovers (if any) will be closed at tomorrow's open.")
    else:
        log(f"Flattening all positions: {[x['symbol'] for x in api.positions()] or 'none'}")
        api.close_all()
        time.sleep(30)

    orders = api.orders(status="all", after=at("00:00").isoformat(), nested="true", limit=500, direction="asc")
    rows = []
    for o in orders:
        if not (o.get("client_order_id") or "").startswith("orb-") or not fill_price(o):
            continue
        sym, side = o["symbol"], o["side"]
        stop_leg = next((lg for lg in (o.get("legs") or []) if lg.get("type") == "stop"), None)
        if stop_leg and fill_price(stop_leg):
            exit_px, how = fill_price(stop_leg), "stopped"
        else:
            closers = [c for c in orders if c["symbol"] == sym and c["side"] != side and fill_price(c)
                       and c["id"] != o["id"] and c["created_at"] > o["created_at"]]
            exit_px, how = (fill_price(closers[-1]), "eod") if closers else (None, "open")
        rows.append(dict(date=now().date(), ticker=sym, side="long" if side == "buy" else "short",
                         entry=fill_price(o), exit=exit_px, shares=int(float(o["filled_qty"])),
                         stop=float(stop_leg["stop_price"]) if stop_leg else None,
                         setup=orb.MODEL_ID, notes=how))
    if not rows:
        return log("No trades today.")
    df = pd.DataFrame(rows)
    path = JOURNAL / "trades.csv"
    if path.exists() and str(now().date()) in set(pd.read_csv(path).date.astype(str)):
        return log("Today's trades are already journaled (duplicate run).")
    df.to_csv(path, mode="a", header=not path.exists(), index=False)
    done = df.dropna(subset=["exit"])
    sgn = done.side.map({"long": 1, "short": -1})
    pnl = ((done.exit - done.entry) * done.shares * sgn).sum()
    log(f"Journal: {len(df)} trade(s) today, realized P&L ${pnl:,.2f}")
    stats = subprocess.run([sys.executable, str(HERE.parent / "trading-prompts" / "journal_stats.py"), str(path)],
                           capture_output=True, text=True)
    (JOURNAL / "STATS.md").write_text(f"# Live Paper Journal Stats\n\nUpdated {now():%Y-%m-%d %H:%M} ET\n\n```\n"
                                      f"{stats.stdout or stats.stderr}```\n")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("open", "close", "flatten"):
        sys.exit(__doc__)
    api, p = Alpaca(), orb.Params()
    if mode == "flatten":
        log(f"MANUAL FLATTEN: closing {[x['symbol'] for x in api.positions()] or 'nothing'}")
        return api.close_all()
    open_session(api, p) if mode == "open" else close_session(api, p)


if __name__ == "__main__":
    main()
