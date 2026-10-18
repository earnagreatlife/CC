# Backtest Results: Real Historical Data Only

All tests use actual daily OHLCV market history. No synthetic or mock data.

| File | Instrument | Range | Bars | Source |
|---|---|---|---|---|
| `data/SP500_1999-2018.csv` | S&P 500 index (^GSPC) | 1999-01-04 → 2018-12-31 | 5,031 | Yahoo Finance, via the `arch` Python package's bundled dataset |
| `data/NASDAQ_1999-2018.csv` | NASDAQ Composite (^IXIC) | 1999-01-04 → 2018-12-31 | 5,031 | Yahoo Finance, via `arch` |
| `data/GOOG_2004-2013.csv` | Alphabet/Google stock | 2004-08-19 (IPO) → 2013-03-01 | 2,148 | `backtesting.py` test dataset |

Settings: 5 bps cost per side, fills at the next day's open, long-only. The first 70% of each
history is in-sample (IS) and the last 30% is out-of-sample (OOS). Index prices exclude dividends,
which hurts buy & hold slightly more than the strategies. Full output: `data/backtest_output.txt`.
Reproduce: `python3 backtest.py data/SP500_1999-2018.csv --strategy sma --fast 50 --slow 200 --split 0.7`

## Out-of-sample CAGR vs buy & hold (the test that matters)

| Strategy | S&P 500 2013–18 | NASDAQ 2013–18 | GOOG 2010–13 |
|---|---|---|---|
| SMA 50/200 crossover | +8.4% (B&H +9.4%) | +11.9% (B&H +13.5%) | −1.0% (B&H +20.0%) |
| RSI(14) buy<30 / sell>55 | +3.7% (B&H +9.4%) | +4.2% (B&H +13.5%) | +1.3% (B&H +20.0%) |
| 55/20-day breakout | +0.2% (B&H +9.4%) | −1.4% (B&H +13.5%) | ~0% (B&H +20.0%) |

## What the real data says

1. **Out of sample, no strategy beat buy & hold on return. That's 9 out of 9 tests.**
2. **The 50/200 SMA is a drawdown tool, not a return tool.** In-sample (1999–2012, which includes
   two bear markets) it cut the S&P max drawdown from −56.8% to −20.3% and the NASDAQ's from −77.9% to −37.3%,
   and it beat buy & hold. In the 2013–18 bull market it gave back about 1–1.5% a year of return for less drawdown.
3. **The sample sizes are too small to trust.** SMA produced 3–9 trades per window, and almost every run triggered the
   "<30 trades, not statistically meaningful" warning. A profit factor of 117 from 8 trades means nothing.
4. **The breakout looks overfit.** NASDAQ IS profit factor 2.59 fell to 0.83 OOS. That's the collapse prompt #4 is designed to catch.
5. **Mean reversion (RSI) doesn't hold up across instruments.** It made money on the S&P but lost on GOOG (IS PF 0.27).

**Conclusion:** with real data, the "high-probability setup" claims behind the original prompts don't
hold up. A simple trend filter is useful for **risk control**, not for beating the index. Any AI
answer that reports a 70%+ win rate without running code like this should be treated as made up.

## Not yet tested

- `journal_stats.py` needs your actual trade log. Nothing here is fabricated to stand in for it.
- Data after 2018: the market-data sites (Yahoo, Stooq, FRED) are blocked from this build environment.
  Drop a fresh CSV into `data/` and rerun.
