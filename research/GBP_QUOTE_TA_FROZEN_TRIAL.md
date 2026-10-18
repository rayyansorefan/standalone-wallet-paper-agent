# Frozen prospective spot-quote technical comparison — 18 October 2026

**Scope: research-only. Not an instruction to resume GBP trading.** The original GBP allocation suspension, all 81+ historical closes, GBP position exits, the separate USD paper futures ledger, and the current paired USD experiment remain unchanged.

## Why a technical study rather than fitting the eleven winners

The full original GBP ledger examined at saved cycle 763 contains 81 closed trades: 16 wins, 65 losses and -GBP 23.4774 realised. The eleven most recent winning exits sum to +GBP 19.8727 but came from seven distinct pools; only four have entry technical snapshots and only two share the current policy regime. Nine take-profit wins in older regimes cannot validate changing current exits. Current matching policy has 19 closes, two wins, 17 losses, -GBP 8.3856 net: approximately -GBP 4.6671 gross price movement plus GBP 3.7185 modelled execution cost. Looking at winners alone is selection bias.

The combination of net costs and poor signal selection, not a lack of scheduler activity, requires a genuine prospective, comparable experiment. Historical RSI/EMA/MACD at entry CANNOT be reconstructed from current quotes for old trades; no OHLC reconstruction or invented candles.

## Independent research guiding the questions

- Moskowitz, Ooi & Pedersen, *Time Series Momentum* (Journal of Financial Economics 2012): time-series trend effects may exist in liquid futures over long horizons, not proof for five-minute Solana pools. DOI: 10.1016/j.jfineco.2011.11.003
- Fieberg, Liedtke & Zaremba, *Cryptocurrency anomalies and economic constraints* (International Review of Financial Analysis 2024): microcap/liquidity costs can eliminate apparent anomalies and effects can decay. DOI: 10.1016/j.irfa.2024.103218
- Deprez & Frömmel, *Are simple technical trading rules profitable in bitcoin markets?* (International Review of Economics & Finance 2024): large rule universes require cost-aware out-of-sample testing and multiple-testing control. DOI: 10.1016/j.iref.2024.05.003
- *Technical analysis in cryptocurrency markets: Do transaction costs and bubbles matter?* (Journal of International Financial Markets, Institutions and Money 2022): market conditions and costs alter technical-rule results. DOI: 10.1016/j.intfin.2022.101601

Six-figure weekly trader marketing claims, partial wallet histories, screenshots and copied winning addresses are not verified executable net returns. Neither shorting a DEX spot token nor Helius signature connectivity is an executable trading rule without suitable independent venue/cost data.

## Registered forward hypotheses

The study `agent/gbp_quote_ta.py` consumes **only genuinely fresh prices already fetched by the existing paper cycle**. It adds zero market, security, or paid API requests and never touches account decisions. At least 35 contiguous roughly five-minute *polled observations* are required per pool; observations separated by over eight minutes reset that pool's technical indicator window. Maximum 100 tracked pools, 48 price observations each. These are **not OHLC exchange candles** and do not measure intrabar highs/lows or realised executable bid/ask fills.

Four fixed, comparative long-only hypotheses:
1. **Sampled-quote control:** all fully featured sampled pools, a descriptive baseline, NOT an executable strategy.
2. **EMA/MACD continuation:** EMA12 > EMA26, MACD(12,26) > signal9, RSI14 50–70, last observed return 0.2–2.5%.
3. **Observed-high breakout:** close above maximum of preceding twenty polled five-minute prices, MACD > signal, RSI14 55–80. This is NOT a genuine candle-high breakout.
4. **Oversold reversal:** RSI14 20–35, price below EMA26, latest observed price change negative. This is not proof of a bottom.

Each arm uses the **same prospective quote event and 5/30/60-minute windows**. Costs: adverse 1% each side; separate extra 2 percentage-point stress. Missing or late future marks remain unpriced/missing. At most ten study admissions per cycle, once per pool per hour, with source/definition digest and zero auto-promotion. Actual spot GBP fills, spreads, slippage, safety-screening and futures short execution are NOT tested here. The zero-trade option is a valid baseline and remains safer than a negative-expectancy GBP policy.

## Review gate

Never infer predictive power merely from historical fit, a few quote returns, or fewer trades. Assess >=100 genuinely prospective well-observed candidate outcomes across >=14 distinct days, pool/day clusters, transaction-cost/stress sensitivity, and a separate frozen time-forward holdout. Include invalid/missing quotes, repeat pools and the best-day exclusion. Only then propose a separately reviewed simulated GBP release with an entry/exit implementation; do not silently clear the loss suspension, automatically promote or alter stop/sizing policy. If results remain net negative, reject all tested variants and keep GBP allocations suspended.

The compact `docs/health.json` field `gbp_quote_ta` exposes only aggregate evidence; raw pool/token identities stay in the persisted state rather than published health. No strategy returns are claimed from these sampled quote diagnostics.
