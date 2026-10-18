# Trading Prompt Pack (v2)

Upgraded versions of the 7 "AI trading" prompts going around on Facebook.

## The flaw that sinks the originals

They ask a chat model to *scan today's market*, *read the charts* and *run a backtest*.
Unless you give it data, it has no live prices, no charts and no price history. So it
**invents** levels, win rates and drawdowns, and states them with full confidence. That
is worse than useless, because the made-up numbers look like research.

**Fix:** every prompt below either (a) has you paste the real data in, or (b) sends the
number-crunching to code (`backtest.py`, `journal_stats.py`) and uses the model only to
interpret the results. Every prompt also has a **no-fabrication clause** and a **kill
condition**, the price at which the idea is wrong.

### Shared header (paste at the top of any prompt)

```
RULES:
- Use ONLY the data I provide below, plus live web/tool access if you actually have it.
  If you don't have a number, write "NO DATA". Never estimate prices, levels or stats.
- Show the date/time of the most recent data point you are using.
- Every trade idea needs: entry, stop (invalidation), target, R:R, position size at
  {RISK_PCT}% account risk on a {ACCOUNT_SIZE} account, and the condition that kills it.
- If the honest answer is "no trade", say "no trade". Don't force setups.
- End with the 3 biggest ways this analysis could be wrong.
```

How to get data quickly: on Yahoo Finance or Stooq, open the ticker, go to Historical
Data, download a daily CSV, and paste in the last 120 rows or attach the file. On TradingView,
note the key levels yourself and paste them in.

---

## 1. Trade Idea Screener (replaces "Trading Ideas Generator")

Original problem: it asks for "5 high-probability setups" from a market the model can't see.
A fixed quota of 5 also forces it to pad the list with weak setups.

```
[SHARED HEADER]

Universe: {TICKERS or SECTOR}. Style: {swing 2–10 days | day trade}. Account {ACCOUNT_SIZE}, risk {RISK_PCT}% per trade.

Data for each ticker (last 60 daily bars, OHLCV):
{PASTE CSV ROWS}

Upcoming catalysts I know of (earnings dates, macro events):
{PASTE or "none known"}

Task:
1. Compute 20/50 SMA, 14-day RSI, 14-day ATR, and the 20-day high/low for each ticker. Show the values.
2. Return UP TO 5 setups (zero is fine) that meet ALL of these: R:R ≥ 2, stop ≥ 1 ATR from entry,
   no earnings inside the holding period.
3. Use this table for each setup: Ticker | Direction | Setup type | Entry trigger (exact
   condition, not just a price) | Stop | Target 1 / 2 | R:R | Shares at my risk | Kill condition | Confidence (Low/Med/High) and why.
4. Rank the setups. Explain why #1 beats #2 in one sentence.
```

## 2. Technical Analyst

The original says "analyze using daily and weekly charts" without supplying any charts.

```
[SHARED HEADER]

Ticker: {TICKER}. My timeframe: {holding period}. Current position: {none | long X @ Y}.

Daily OHLCV, last 200 bars: {PASTE}
(Weekly bars, optional: {PASTE}; if you leave this out, the model resamples the daily data)

Task:
1. Trend state on weekly, then daily: higher highs/lows? Price vs 20/50/200 SMA. Slope of the 50.
2. Support/resistance: list at most 3 levels each side. Give the date(s) each was tested and why it matters.
   Reject any level with fewer than 2 touches.
3. Momentum: RSI(14), MACD(12,26,9). Report divergences only if they show up at swing points.
4. Signal: BUY / HOLD / SELL / NO EDGE, with:
   - the single strongest reason for it
   - the strongest reason against it (steelman the opposite trade)
   - the exact trigger, stop, target and R:R
   - what would flip the signal
5. If my position is not "none": manage it. Hold, trim or exit, and where to move the stop.
```

## 3. News → Trade Translator

The original says "summarize the latest news", but without browsing the model only knows its
training data, which can be months old.

```
[SHARED HEADER]

Company/sector: {NAME}. Today's date: {DATE}.
News items (paste headline + date + source + key paragraph, or links if you can browse):
{PASTE}
Price reaction so far: {e.g. "-4.2% today on 3x avg volume"}

Task, for each item:
1. What actually changed? Classify it: earnings/guidance | product | legal/regulatory | macro | management | noise.
2. Is it priced in? Compare the news with the price/volume reaction I gave you.
3. Second-order effects: who else wins or loses (suppliers, competitors, ETFs)?
4. Implied move: give the expected range ONLY from data I provided (options implied move, historical
   reaction to similar events). Otherwise write "NO DATA". Don't guess percentages.
5. Positioning: short term (days) and long term (months). Give the action, the instrument
   (stock / options / pair trade / do nothing), and the kill condition.
Finish with: "The market is probably wrong about ___ because ___", or "No edge here."
```

## 4. Strategy Backtester (use the script, not the chat)

A chat model **cannot** honestly backtest from memory. Any win rate it gives you without running code is made up.
Run `backtest.py` (in this folder) on real data, then give the output to the model:

```bash
python3 backtest.py data/SPY.csv --strategy sma --fast 50 --slow 200 --cost-bps 5
python3 backtest.py data/SPY.csv --strategy rsi --rsi-buy 30 --rsi-sell 55 --cost-bps 5
python3 backtest.py data/SPY.csv --strategy sma --fast 20 --slow 50 --split 0.7   # in/out-of-sample
```

If your AI tool can run code (Claude analysis tool, ChatGPT Advanced Data Analysis),
attach the CSV and `backtest.py`, then use:

```
[SHARED HEADER]

Here are backtest results for {STRATEGY} on {TICKER}, {DATE RANGE}, with costs included:
{PASTE backtest.py OUTPUT}

Task:
1. Is there an edge? Compare with buy-and-hold on return, max drawdown and return/drawdown.
2. Overfitting check: compare in-sample and out-of-sample results. If OOS profit factor falls by >30%, say so plainly.
3. Is the sample big enough? Fewer than 30 trades means "statistically meaningless". Say that directly.
4. Suggest at most 3 changes, each with the hypothesis behind it and the exact backtest.py command to test it.
   Don't suggest changes you can't test with this script.
```

## 5. Portfolio Risk Manager

The original gives the model no prices, no correlation data and no limits, so it can't size anything.

```
[SHARED HEADER]

Portfolio (ticker | shares or $ value | % weight | cost basis):
{PASTE}
Cash: {X}. Total value: {X}. Max drawdown I can stomach: {X%}. Time horizon: {X}. Tax account type: {taxable/IRA}.
Optional: 1y daily closes for each holding so you can compute real correlations: {PASTE or attach CSV}

Task:
1. Concentration: largest single name, sector and factor exposures (growth/value, rates, USD, oil).
2. Hidden correlations: compute them from the data if I supplied it. If not, label each pair "assumed" and keep it qualitative.
3. Stress test a -20% market drop: estimate the portfolio drawdown with beta (show the betas you used and where
   they came from), then a 2022-style rates shock and a 2020-style crash.
4. Rebalance: give the exact trades (ticker, buy/sell, $ amount) and how much each one cuts the stressed drawdown.
5. Hedge options, cheapest first, with approximate cost as % of portfolio per year: cash raise, index puts or
   put spreads (strike/expiry), inverse ETF, collar. Use "NO DATA" for option prices I didn't give you.
6. One-line verdict: "If the market drops 20% tomorrow, I lose about $___."
```

## 6. Trading Journal Analyzer

The original asks the model to do arithmetic across 20 trades, which is where models make mistakes.
Run `journal_stats.py` first so the numbers are exact:

```bash
python3 journal_stats.py my_trades.csv
```

CSV columns: `date,ticker,side,entry,exit,shares,stop,setup,notes`. `stop` is optional but recommended.
`notes` should say how you felt (FOMO, revenge, bored, etc.).

```
[SHARED HEADER]

Here are my journal stats and raw trades:
{PASTE journal_stats.py OUTPUT}
{PASTE CSV}

Task:
1. Where does the P&L come from? Name the setup(s) or condition(s) that make the money and the ones that lose it.
2. Recurring mistakes, each with the trade numbers as evidence: early exits, moved stops, oversizing,
   revenge trades after losses, trading outside my setups. Use the R-multiples and the notes column.
3. Behavioral biases you can actually see in the data (cite the trades). Don't diagnose biases without evidence.
4. Exactly 3 rules. Each must be mechanical and checkable, e.g. "No new trade within 60 min of
   a −1R loss", not "be more disciplined". For each rule, show what my P&L would have been if I'd followed it.
5. Which single setup should I trade more, and which should I stop trading?
```

## 7. Daily Trading Plan

The original says "trade like a professional", but professionals start from risk limits. This version makes the plan follow those limits.

```
Market/asset: {e.g. US equities, ES futures, BTC}. Session: {timezone, open/close times}.
Account: {SIZE}. Max risk per trade: {X%}. Max daily loss: {X% or $}, after which I stop for the day.
Max trades per day: {N}. My A+ setups: {list 1–3}. Hours I can actually trade: {X}.

Build a daily checklist with timestamps in my timezone:
- PRE-MARKET (T-60 to T-0): economic calendar, earnings, overnight range, key levels, watchlist ≤ 5,
  and an if/then plan for each name.
- OPEN (first 30–60 min): what I'm allowed to trade, opening-range rules, and when to stay out.
- MID-SESSION: rules for managing open trades, plus the "no new trades if…" conditions.
- CLOSE: what gets flattened or held overnight and why, then the journal entry.
- HARD STOPS (always on top): daily loss limit, max trades, no averaging down, no trading the 2 min around
  scheduled news.
- POST-SESSION (10 min): 3 journal questions, plus the one thing to fix tomorrow.

Keep it to one screen. Format each item as a checkbox I can tick, with no explanations.
```

---

## The bar these prompts are built to meet

- **No invented numbers.** Every figure comes from data you supplied or from code that was actually run.
- **Every idea has an exit.** Stop, target, size and kill condition, or it isn't an idea.
- **"No trade" is an allowed answer.** The original prompts force output. These allow the honest one.
- **The arithmetic is done in code.** Backtest stats and journal stats come from scripts.

*Not financial advice. Backtests are hypothetical, and past results don't predict future returns.*
