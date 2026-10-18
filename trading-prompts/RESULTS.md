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

---

# Round 2: The "Dynamic Algo" (walk-forward adaptive)

`walkforward.py` tests the idea that an algorithm adapting to history can be accurate and consistent.
Each year it scores **28 strategy/parameter combos** (SMA, RSI, breakout, buy & hold) on the prior
3 years only, then trades the winner over the next year, which it has never seen. Every number below is out-of-sample.
It's compared against an **equal-weight ensemble** (all 27 non-buy-and-hold combos averaged, with no selection), the plain 50/200 SMA and buy & hold.
The engine was cross-checked against `backtest.py`: it reproduces the same +221.5% / −20.3% on S&P 500 SMA 50/200.

| Data (OOS years) | System | CAGR | Max DD | Sharpe | Worst year |
|---|---|---|---|---|---|
| S&P 500 2002–18 | **Adaptive** | +2.3% | −30.1% | 0.25 | −10.8% |
| | Ensemble | +3.2% | −13.5% | 0.48 | −4.2% |
| | SMA 50/200 | +6.5% | −20.3% | 0.61 | −6.3% |
| | Buy & hold | +4.6% | −56.8% | 0.33 | −38.5% |
| NASDAQ 2002–18 | **Adaptive** | +1.0% | −51.0% | 0.14 | −34.5% |
| | Ensemble | +4.2% | −22.3% | 0.53 | −12.6% |
| | SMA 50/200 | +7.1% | −24.6% | 0.57 | −11.5% |
| | Buy & hold | +7.2% | −55.6% | 0.43 | −40.5% |
| GOOG 2007–13 | **Adaptive** | +1.0% | −44.2% | 0.15 | −29.1% |
| | Ensemble | +3.3% | −37.2% | 0.31 | −28.9% |
| | SMA 50/200 | +1.0% | −42.7% | 0.15 | −35.6% |
| | Buy & hold | +9.0% | −65.3% | 0.42 | −55.5% |

With 12% volatility targeting (`--vol-target 0.12`), drawdowns shrink a lot (ensemble: −8.8% / −9.1% / −13.6%)
and returns fall roughly in proportion. Full output: `data/walkforward_output.txt`.

## Verdict

1. **The dynamic selector was the worst or tied-worst system on all 3 datasets.** Choosing last period's
   winner is performance chasing: the picks change almost every year (see the log) and keep buying high.
2. **Not choosing beats choosing.** The ensemble had about half the adaptive system's drawdown and a higher Sharpe on all 3.
3. **Nothing beat buy & hold on raw return over the full period,** except the SMA on the S&P (+6.5% vs +4.6%), and that rule
   was famous before this test, so it's partly a hindsight pick.
4. **What's achievable:** much smaller losses for similar or lower return. Max drawdown drops from −57% to between −9% and −20%.
   "Amazingly accurate" is not achievable. Any backtest showing that has leaked future data or been overfit.
5. **Trap to avoid:** a 5-year training window looks better on the S&P (+4.9%). Picking that window *after seeing the result*
   is the same overfitting all over again. The defaults were fixed before the run.
