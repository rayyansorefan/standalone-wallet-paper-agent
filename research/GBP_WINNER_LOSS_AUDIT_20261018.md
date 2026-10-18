# GBP paper strategy forensic review and prospective research registration

Research timestamp: 18 October 2026. **No live trading, no strategy promotion, no original-ledger reset.** Recorded values are sampled snapshots that will advance independently as previously opened positions exit. The audit and assumptions below precede the new GBP prospective signal lab.

## Verified existing GBP ledger (state at cycle 754, 14:34 UTC)

- **80 closed original GBP paper trades**: 16 net winners, 64 net losers; all-time **−£23.0167** realised. This is not the independent USD futures account.
- Wins: **+£30.7316** gross sum of recorded *net* winning-trade results (average +£1.9207). Losses: **−£53.7483** (average −£0.8398). At that payoff ratio, a naive break-even winner frequency is about **30.4%**, versus observed 20%. Do not mistake this naive figure for a forecast or for the new-policy break-even ratio.
- **The last 11 recorded winning trades** sum to **+£19.8727** and cover **seven distinct token pools**. Seven of the 11 closes are repeated entries from only three token pools; repeated events are not independent evidence. Nine of the 11 used legacy/mixed exit regimes, **two** have matching current audited economic policy labels. Only **four** of the eleven have full saved entry technical snapshots. Therefore a 'perfect filter' fitted to eleven winners would be retrospective data leakage.
- Current audited **18 closed-trade cohort**: two winners, 16 losers; **−£7.9249** net. Entry/exit gross price movement **−£4.4016**, execution-cost drag **£3.5233**. Thirteen observed −4.5%-net stop exits in this cohort lost −£8.0777 together; actual sampled stops can overshoot, and the 4.5% level is NOT guaranteed fill.
- Legacy/mixed 62-close cohort: recorded gross price movement **−£2.746**, modelled cost drag **£12.3458**, net **−£15.0918**. Old 20% take-profit wins and 12% stop-outs must never be combined as if they came from current entries/exits.
- Current-policy win 2/18 is not a reliable basis for optimisation. A later read had 19 current-policy closes **from one exit date**; it still did not support a winning technical subset. In exploratory same-sample checks, a >=2.02% five-minute move selected 6 closes (1 win, net −£3.04), >=55% buys selected 6 (zero wins, net −£2.89); strict acceleration selected zero. THESE ARE FAILED IN-SAMPLE DIAGNOSTICS, NOT VALIDATED ALTERNATIVES.

### Distinct hypotheses tested, not rules to deploy

The engine's 1% entry plus 1% exit modelling creates approximately a 2.02% break-even spot-price rise from an unchanged mark. The historical 11 winners skew toward old 20% profit-taking exits, while recent losses often lack sufficient favourable excursion to beat costs. A shorter signal delay alone did not discriminate in the current one-day sample. Large 5m/1h momentum, higher hourly volume pace and higher buy fraction individually did not consistently separate current wins from losses. Several losers briefly became gross-positive yet failed to retain *net* gains; exit counterfactuals require fresh path quotes and cannot be reconstructed from a closing price alone.

Existing `decision_v1.forward_outcomes` at the audited snapshot recorded **251** forward observed opportunities (29 nominally accepted / 222 blocked) but only sparse matching signal-time feature records, plus missing 30/60-minute quote outcomes. It reports average *quote* net ROI for accepted signals around −2.02% at 5m, −1.73% at 30m and −3.45% at 60m, not executable strategy returns. Future unpriced observations must remain missing; past signals MUST NOT be labelled from later metadata.

## Independent research considered

The relevant reproducible findings are about strategy classes, not unverifiable claims that particular wallets earn six figures every week:

1. **Cross-sectional momentum versus reversal:** Wen et al., *North American Journal of Economics and Finance* (2022), DOI 10.1016/j.najef.2022.101733: both mechanisms occur but vary by jumps, liquidity and market conditions. Do not presume all pumps continue or all fades revert.
2. **Breakout/MA and costs:** *Technical analysis in cryptocurrency markets: Do transaction costs and bubbles matter?* (2022), https://www.sciencedirect.com/science/article/pii/S1042443122000816: net transaction costs remove many apparent winning technical rules. Current account exhibits material two-sided cost drag.
3. **Returns, liquidity and risk:** Mercik et al., *International Review of Financial Analysis* (2025), DOI 10.1016/j.irfa.2024.103809: momentum, liquidity and risk interactions can matter out of sample; thin liquidity materially erodes returns.
4. **Momentum crashes:** Grobys et al., *Financial Markets and Portfolio Management* (2025), DOI 10.1007/s11408-025-00474-9: momentum portfolios suffer tail risk and large crashes; cost-aware risk screening cannot be dropped.
5. **DEX manipulation:** *Price manipulation schemes of new crypto-tokens in decentralized exchanges* (2025), DOI 10.1140/epjds/s13688-025-00602-5: extreme winners and low-liquidity price changes are exposed to manipulation and MEV. Do not substitute transaction-count pressure for token safety or executable depth.
6. **Large-scale rule selection:** Deprez & Frömmel (2024), DOI 10.1016/j.iref.2024.05.003: thousands of technical rules and multiple-testing concerns; training results alone are not sufficient.
7. **Time-of-day momentum/reversal:** *On the Performance of Lagged Momentum and Reversal Strategies Across Daytime and Overnight Sessions in Bitcoin and Ethereum* (2026), https://www.mdpi.com/1911-8074/19/9/692: searching multiple windows makes out-of-sample confirmation essential; some apparent advantages were not statistically significant.

Trader-style approaches to test as **distinct hypotheses**, not to assume profitable: momentum breakout with volume, price pullback/reclaim, mean reversion after exhaustion, fade-short after pump peak, cross-sectional momentum ranks, whale-following with causally fresh confirmed flows, and no-trade/control. Some require historical candles, an actual shortable instrument, executable spread/depth, or independently timestamped wallet records. Those absent inputs mean **NOT TESTABLE** with the existing GBP five-minute pool snapshots; do not invent OHLC, fills, wallet profitability or claim every top trader has been replicated.

## Separate *prospective* GBP research implementation

`agent/gbp_signal_lab.py` registers a frozen hypothesis fingerprint on the first unattended cycle after deployment. `agent/decision.py` freezes initial pool technical features with each *new* forward signal, before the engine sees future returns. Zero paid requests or trading changes. For each 5/30/60-minute horizon, reports count, priced, missing and pending marks, cost-adjusted quote win fraction, mean return, additional cost stress, distinct days and pools. The predeclared LONG-only comparator arms are original gate, moderate momentum, accelerating breakout, high-volume trend, buyer pressure and more-liquid confirmation; this is deliberately a **limited defensible comparison**, not 'every successful trader' or a statistically proven execution backtest.

Existing older signals without a genuine admission-time feature snapshot are excluded rather than post-hoc fitted. A source/hypothesis mismatch invalidates the research; it cannot silently restart. Safety screens, 1% per-side modelling, GBP portfolio-wide SUSPENDED allocation, USD futures, immutable history and existing paired trial all remain unchanged. Quote returns are **not executable profits**, and 100+ independent, cross-day actual-equivalent observations with a frozen OOS split, adequate pool/day clustering and stressed net gain are necessary even to *request independent review*. Automatic strategy promotion is always false.

## Decision now

- **Keep existing GBP new entries and additions SUSPENDED**. Keep correctly monitoring and exiting any positions already open. Do not restart an unprofitable portfolio based on historical patterns.
- Let independent quote-only hypotheses gather genuinely fresh, security-gated, cost-adjusted outcomes over multiple regimes and dates. Preserve 'no trade' at zero as a legitimate comparator; absence of trades is not proof of skill.
- Preserve independent USD futures comparison and its source fingerprint. The GBP research signal lab is not an alteration of the USD engine and must not invalidate its ongoing trial.
- If forward research shows no positive prospective edge, explicitly report failure and do not promote or fabricate trades.

This research does not support the claim that a reliably profitable new strategy has been found or that a specific famous trader's realised P&L is replicable.
