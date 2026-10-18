# White-paper delivery and prospective trial

Owner mandate, 18 October 2026: autonomy, positive self-improvement, more wins than losses. Software health is not profitability. No real orders, paid services, reset accounts, concealed losses or speculative risk escalation.

## What this change delivers

`agent/forward_experiment.py` runs on each successful futures quote cycle without any extra provider requests. It uses two separate, fresh $2,000 simulated ledgers. They are not deposits, additional real capital, or a reset of either existing account. Original GBP and existing USD positions/history remain intact.

- Baseline: existing momentum-fade-2 engine and its deterministic feedback, starting at registration; this is NOT a GBP wallet-copy benchmark.
- Challenger: same engine, universe, observations, fees, slippage, funding reserve, size limits, stops and holding rules; admissions restricted to momentum after a completed previous-bar pullback to EMA6 and current close reclaim, within 1 ATR of EMA6 and spread <=0.1%. Fade entries are excluded. This tests an entire restrictive admission policy, not the isolated causal effect of one feature.
- Existing momentum tests (including hourly/15-minute trend, activity and cost room), news veto, setup loss suspension and daily controls still apply to both arms.
- Fixed duration: 28 days from the first genuine observation. No retrospective trades. Deadline blocks new entries and additions; observed exits continue. Insufficient sample at the deadline stays insufficient; no opportunistic extension.
- Each arm stops new entries/additions after observed equity falls $40 below its own start. This is a latched research loss budget, not a guaranteed maximum loss: sampled stops can gap. No automatic reset or funding replenishment.
- Hash of economic source is recorded before the first admission. Later source changes invalidate comparability and block admissions; management continues and history is retained. No silent new epoch.
- Atomic paired state update; duplicate timestamps do nothing. Errors remain visible in compact health without crashing the original trading engine.
- Dashboard and health show both arms, net results, win counts, profit factor, equity difference, status and blocking reason. No results are combined with original GBP or existing USD accounts.

## Admission to further review, not automatic promotion

After the fixed period and final open exits, require at least 100 closes in 100 distinct entry-hour clusters, positive net, profit factor >1.3, win rate >50%, positive stressed net, higher ending equity than baseline, no loss-budget halt and complete observed exit features/marks. Passing these necessary descriptive checks yields REVIEW_REQUIRED_NOT_VALIDATED. Hour clusters do not establish independence. A day-clustered uncertainty analysis, excluding the best trade/day, multiple-testing accounting and genuinely fresh confirmation remain required before any selection promotion. No risk multiplier increases.

No claim that this trial is a profitable strategy, a complete learning programme or completion of the white paper. Four weeks is an evidence collection floor for an adequately sampled trial, not a promise of success. Failure or sparse signals are legitimate outcomes. Do not force trades to meet a quota.

## Known limitations to monitor

The inherited feed scans up to six candle instruments chosen by the existing engine. Both trial arms see the same available inputs; held shadow instruments may lose candle coverage even when their ticker remains available. Such missing exit features or marks are counted and block review qualification. Do not conceal this limitation, use stale candles as fresh, or increase provider budgets without a tested design. The existing funding reserve is an adverse estimate, not actual venue funding settlement. Stops execute only at observed quotes. A successful backtest or software test cannot prove achievable fills.

## Remaining delivery queue

1. Verify two independent Google-triggered post-merge runs, paper/dashboard success, state continuity, trial registration, incrementing cycles and no experiment errors. Record run IDs in the shared AUTO-HEALTH work queue; do not require the user to relay reports.
2. Diagnose original GBP losses by immutable entry/exit policy epoch, gross move versus modeled costs, signal delay and stop overshoot. Preserve mixed legacy labels; never treat history as same-policy forward validation. Do not silently replace the original account's strategy with this futures experiment.
3. Complete archive/reconciliation work so lifetime records cannot disappear behind rolling buffers.
4. Implement the separately predeclared earlier profit-retention exit comparison on identical prospective entries, after tests and a separate source/version boundary. Do not contaminate the active paired trial or mine its outcomes to tune it.
5. Complete common frozen OOS, day-clustered and baseline-relative certification. Only evidence-supported bounded selection may be considered; position risk is not a reward for a short winning streak.
6. Dashboard payload/retention/chart gaps and seven-day scheduler SLO remain open. Helius connectivity is independent of strategy edge and must not be presented as the missing ingredient for profits.

## Autonomous maintainer operating rule

Read this file and the shared [AUTO-HEALTH] issues before acting. The October 18 instruction authorizes implementing the white-paper programme and isolated prospective strategy experiments; the earlier blanket prohibition on experiments is superseded. Preserve existing capital/risk limits and ledger histories. Never repeatedly retune a running trial, claim automatic cross-chat handoff, or close the profitability issue because infrastructure is green. Repair reproducible defects with regression tests and CI, verify unattended execution, and report only materially verified changes or exact external blockers. Maintain a single shared queue rather than duplicate chat instructions.
