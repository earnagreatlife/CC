"""Minimal Alpaca REST client (trading + market data). Paper endpoint unless explicitly overridden."""
import os
import time

import pandas as pd
import requests

PAPER = "https://paper-api.alpaca.markets"
LIVE = "https://api.alpaca.markets"
DATA = "https://data.alpaca.markets"
LIVE_OPT_IN = "I_ACCEPT_REAL_MONEY_RISK"


class Alpaca:
    def __init__(self):
        key, secret = os.environ.get("ALPACA_KEY"), os.environ.get("ALPACA_SECRET")
        if not key or not secret:
            raise SystemExit("Set ALPACA_KEY and ALPACA_SECRET (Alpaca dashboard -> API keys).")
        self.live = os.environ.get("ALPACA_LIVE") == LIVE_OPT_IN
        self.base = LIVE if self.live else PAPER
        self.s = requests.Session()
        self.s.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})

    def _req(self, method, url, **kw):
        for attempt in range(5):
            r = self.s.request(method, url, timeout=30, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"{method} {url} -> {r.status_code}: {r.text[:300]}")
            return r.json() if r.content else None
        raise RuntimeError(f"{method} {url} failed after retries")

    # --- trading ---
    def clock(self):
        return self._req("GET", f"{self.base}/v2/clock")

    def account(self):
        return self._req("GET", f"{self.base}/v2/account")

    def positions(self):
        return self._req("GET", f"{self.base}/v2/positions")

    def submit(self, **order):
        return self._req("POST", f"{self.base}/v2/orders", json=order)

    def orders(self, **params):
        return self._req("GET", f"{self.base}/v2/orders", params=params)

    def close_all(self):
        return self._req("DELETE", f"{self.base}/v2/positions", params={"cancel_orders": "true"})

    def asset(self, symbol):
        return self._req("GET", f"{self.base}/v2/assets/{symbol}")

    # --- market data ---
    def bars(self, symbols, timeframe, start, end, feed="sip", adjustment="split"):
        """All bars for symbols in [start, end) as a DataFrame (symbol, t[ET], o, h, l, c, v)."""
        params = {"symbols": ",".join(symbols), "timeframe": timeframe, "start": start, "end": end,
                  "limit": 10000, "feed": feed, "adjustment": adjustment, "sort": "asc"}
        rows = []
        while True:
            js = self._req("GET", f"{DATA}/v2/stocks/bars", params=params)
            for sym, bars in (js.get("bars") or {}).items():
                rows += [(sym, b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]) for b in bars]
            if not js.get("next_page_token"):
                break
            params["page_token"] = js["next_page_token"]
        df = pd.DataFrame(rows, columns=["symbol", "t", "o", "h", "l", "c", "v"])
        df["t"] = pd.to_datetime(df["t"], utc=True).dt.tz_convert("America/New_York")
        return df

    def latest_trades(self, symbols, feed="iex"):
        js = self._req("GET", f"{DATA}/v2/stocks/trades/latest",
                       params={"symbols": ",".join(symbols), "feed": feed})
        return {s: t["p"] for s, t in (js.get("trades") or {}).items()}
