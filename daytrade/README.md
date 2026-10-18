# Opening-Bell Day-Trading Bot (paper)

A 5-minute **Opening Range Breakout on stocks in play**, run automatically on an Alpaca
**paper** account. Rules are in `orb.py` (frozen as `orb5-relvol-v1`). The backtest and the
live bot share the same code.

> **Reality check.** Most retail day traders lose money. The published research on this strategy
> (Zarattini, Barbon & Aziz, SSRN 2023–24) is a hypothesis, not a promise. This system is built to
> **find out honestly** whether it works for you, starting with real data and fake money.

## What happens each trading day (ET)
| Time | Action |
|---|---|
| ~8:45 | Bot starts on GitHub, closes any leftover positions at the open, loads 14-day ATR and opening volume |
| 9:35 | Ranks 50 liquid stocks by **relative volume** of the first 5-min bar and picks the top 5 |
| 9:35–10:30 | Green first bar → buys a break of its high. Red → shorts a break of its low. Each entry is sent with its **stop-loss attached at the broker** (10% of ATR) |
| all day | Risk 0.5% of equity per trade. A **2% daily loss** flattens everything |
| 15:55 | Close job flattens everything, writes `journal/trades.csv` and `journal/STATS.md` |

Watch it live: open the **Alpaca app → Paper account** for positions and orders, or open
**GitHub → Actions → "Day-trade bot (paper)"** for the bot's running log.

## Setup (about 10 minutes)
1. Create a free account at **alpaca.markets**. Switch to **Paper Trading** and generate API keys.
2. In GitHub, go to repo **Settings → Secrets and variables → Actions → New repository secret** and add
   `ALPACA_KEY` and `ALPACA_SECRET` (the **paper** keys). Never paste the keys anywhere else.
3. **Run the backtest first:** **Actions → "Day-trade backtest" → Run workflow**. Read the summary.
4. **Gate:** turn on paper trading only if the result is positive **at 3¢ slippage** with more than 200 trades.
   Otherwise the strategy has no proven edge, so stop there.
5. Merge to `main`. The schedule runs every weekday automatically.

## Controls
- **Emergency stop:** Actions → "Day-trade bot (paper)" → Run workflow → mode `flatten`.
- **Pause:** add an empty file `daytrade/KILL` to `main`. The bot won't trade until you delete it.
- **Disable completely:** Actions → the workflow → "…" → Disable workflow.
- Stops are held by the broker, so a crashed bot or a GitHub outage still leaves every position protected.

## Real money
It's off by design. It needs a secret `ALPACA_LIVE` = `I_ACCEPT_REAL_MONEY_RISK` plus **live** keys.
Don't do it before **3+ months** of paper results that match the backtest. In the US, accounts under
$25k are limited to 3 day trades per 5 days (the pattern day trader rule).

## Known limitations
- The free Alpaca feed is IEX-only for real-time data. Relative volume is IEX vs IEX history, while the backtest uses all
  exchanges. A paid data plan (`FEED = "sip"` in `bot.py`) makes live match the backtest exactly.
- The universe was chosen today, which adds survivorship bias to the backtest.
- GitHub's scheduler can start late. The bot refuses to trade if it starts after 9:34 ET.
- Live fills on fast opening moves can be worse than the 3¢ stress test.
