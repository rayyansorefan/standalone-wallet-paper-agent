# Standalone Wallet Paper Agent — research prototype v1

**PAPER TRADING ONLY · £2,000 simulated opening balance · zero real orders · no Floot, Bee Bots, wallet private keys, paid AI models, or exchange credentials.**

> **Current status and evidence:** the original GBP2,000 paper account is persistent and the Google Apps Script five-minute fallback has recorded genuine unattended executions. GitHub native cron remains best effort. V3 public-data availability is provider-dependent and must be assessed from current saved diagnostics. Zero verified whale owners and no demonstrated profitability or causal reinforcement improvement are asserted. See the forward evaluation and provider-health sections of the canonical dashboard.

## First deployment to the supplied repository

Target: `https://github.com/rayyansorefan/standalone-wallet-paper-agent` (a public repository).

**Mac Terminal:**

1. Download and unzip this package to a directory. Open Terminal and `cd` to that unzipped directory.
2. Run `bash deploy_to_github.sh`. This clones the target repository, copies the entire application, runs tests, and commits/pushes if your own GitHub login permits it. It does not require ChatGPT's GitHub integration to have write access. It never modifies Bee Bots.
3. Open the repository's **Actions** tab. Enable Actions if requested; open **Autonomous paper wallet research (5-minute target)** → **Run workflow** on `main`.
4. Ensure the repository's **Settings → Actions → General → Workflow permissions** allows reading and writing repository contents; a workflow `403` during commit is a permissions problem, not a successful update.
5. Once you have confirmed a successful run and `docs/state.json` has changed, open **Settings → Pages → Build and deployment → Deploy from a branch → main /docs → Save**.
6. Open `https://rayyansorefan.github.io/standalone-wallet-paper-agent/` **only after** Pages has published the site. The webpage checks `docs/state.json` every 60 seconds and displays the actual latest data timestamp. Refreshing the page does **not** generate a new market observation.

### In case the deployment script cannot authenticate

You can use GitHub Desktop to clone the repository and copy these files into its working directory (including the hidden `.github/workflows/paper.yml`), then commit and push. A ZIP committed directly to GitHub without extraction will *not* deploy the agent.

## What runs and how often

- A GitHub Actions workflow aims to run every **5 minutes**, using the standard GitHub-hosted Ubuntu runner. Standard GitHub-hosted runners are currently free for **public** repositories under GitHub's terms: https://docs.github.com/en/billing/concepts/product-billing/github-actions . There is no guarantee against a future policy change.
- GitHub scheduled runs can be **delayed or skipped**. The dashboard makes staleness explicit; it does not claim 5-minute real-time data if there is no new observation.
- Each cycle checks **up to 4 liquid Solana pools** and keeps its own deduplicated observed transaction history. It does *not* scan all profitable wallets on Solana.
- The GeckoTerminal free API caches responses for around one minute and has a fluctuating public request limit. No sub-second mirroring is possible with this design.
- A read-only Rugcheck report screens the actual **base-token mint**, not the pool address. Report rejection or unavailability means **no new paper entry**.
- The first cycle is a **bootstrap-only** observation, not a retroactive purchase.
- Subsequent qualified candidate signals can lead to paper buys only when they are less than **240 seconds old**, have at least **three observed wallet events**, and pass the portfolio/risk rules. The transaction sender might be an aggregator, so **wallet attribution and wallet-wide profitability remain unverified**.
- Nominal maximum **five positions**, with **0.5% paper equity per exploratory entry**, potentially increasing to 1.5% only after multiple *closed simulated* positive results. Positions use modeled 1% adverse cost per side, 12% model stop, 20% model target and 6-hour max holding window. Price gaps can exceed these thresholds. These are provisional research parameters, not optimised or proven profitable settings.
- No real-money execution component or live wallet secrets exist anywhere in the code.

## Visualiser

The static GitHub Pages site is at `docs/index.html`, and the changing research snapshot is `docs/state.json`. It is a real auto-refresh dashboard once hosted on Pages, not a fixed screenshot.

Shows starting balance, simulated equity progression, realised P&L, open simulated positions and floating P&L, closed trades, sampled-wallet ranking **based only on our paper outcomes**, market-data health, API failures, delayed/missed signals, and recent decisions with reasons. It deliberately prints **UNAVAILABLE** when mark-to-market pricing is missing and marks the feed **STALE** when observations have stopped.

**Caveat:** The chart is reloaded automatically each minute, but market research only runs on GitHub Actions' best-effort five-minute schedule, and the market data can be delayed.

## Local smoke test

```bash
python3 -m unittest discover -s tests -v
python3 -m agent.cli once
```

The first command uses mocked inputs without network. The second requires access to GeckoTerminal and Rugcheck. On an API failure, inspect the newest `state/state.json` and dashboard health; never interpret 0 trades as a successful strategy.

For an always-on machine with Python 3.12+, `python3 -m agent.cli loop` samples approximately every 5 minutes, but a laptop must remain powered on and connected.

## Minimum criteria before discussing profitability

At least 4–8 weeks of forward paper observations, a sufficient sample of **independent** closed trades, realistic latency and execution costs, maximum drawdown, repeatability across market regimes, comparisons with no-copy and SOL buy-and-hold, alternative slippage scenarios and avoidance of overfitting. If data feed quality, wallet attribution or sample size is inadequate, verdict is **inconclusive**, not “profitable”. No proposed ML / bandit adaptation is currently implemented beyond small sample-size-adjusted exposure rules.

## Important public repository privacy note

This project intentionally publishes observed on-chain wallet addresses and simulated trade data. Do not store personal information or API credentials in GitHub's source tree. GitHub Actions writes `state/state.json` and `docs/state.json` to Git history. If privacy is important, use a different hosting design; switching to a private repo can affect billed Actions minutes.


## Research recovery and forward validation (16 October 2026)

V3 reuses the complete primary pool-discovery response, rotates a maximum 64-pool inventory and scans at most two supplemental pools per cycle. Its transport permits four public requests per cycle with a 25-second budget, 2.1-second minimum spacing, bounded eight-second requests, 15-minute discovery caching and persisted exponential cooldowns (5, 10, 20, 40, 60 minutes). Retry-After can extend a cooldown. No stale quote is used as a fresh entry mark. Primary account/V2 requests have priority and remain unchanged. On GitHub Actions, V3 waits once (at most 60 seconds) until roughly 65 seconds after cycle start, separating its supplemental provider window from primary calls; the 25-second research budget starts after that pause. Freshness uses the actual research-start timestamp. The four-minute job timeout is unchanged. DEX Screener is a free quote-only fallback; aggregate counts never manufacture wallet transactions. Market data attribution: GeckoTerminal and DEX Screener.

Large historical transactions can inform discovery, but cannot create backfilled entries or profits. Fresh observed flows receive later 5/30/60-minute sampled quote returns when prices are available. Transaction-origin addresses remain unverified; multi-pool activity can indicate routing and is not proof of beneficial ownership. Research and shadows never change original account P&L.

Positive wallet/feature sizing now requires both the existing safety gates and registered forward validation. Registration excludes pre-existing trades and entries. A fixed chronological training prefix needs at least 40 closures over 14 days; the next 20 entries must begin after the training exits and span at least seven days. Pool/wallet diversity, positive daily-cluster lower bounds (z=4.2 across at most 256 reports), profit excluding the best win and positive 2%-per-side cost stress are additional requirements. This is an approximate conservative research gate, not a guarantee or evidence of causal improvement. Frozen cohort/outcome changes invalidate certification. Negative/suspension controls retain priority; maximum exposure stays 1.5%. No shadow strategy is automatically promoted.

Exit diagnostics and sampled adverse/favourable price paths are descriptive; missed intracycle extremes, actual owner profits and no-stop counterfactuals remain unknown. A research evaluation failure revokes positive certificates and preserves the paper account. Pages publishes in a separate downstream job; a transient publication failure gets one retry after 10 seconds and can never undo the already saved engine state. The next unattended cycle also republishes.

Validation commands: `python -m unittest discover -s tests -v` and `node infra/google_apps_script/test.mjs`. Never reset state files during deployment or rollback. Revert code only and keep the latest rolling state/history. Current run provenance and health, rather than a successful test alone, determine operational status.

## History-aware entry policy v1 (16 October 2026)

The five-minute scheduler, original account and exits remain in place. A versioned
entry policy now consumes actual net closed outcomes across wallet addresses,
keyed by pool and known base-token mint aliases. All re-entries wait 30 minutes;
a loss waits two hours; three losses with negative daily net, or three consecutive
losses, suspend new entries for that token until 24 hours after its latest loss.
Existing positions retain their exits and are not liquidated merely for being in
a losing historical cohort. Alias coverage is limited to observed pool metadata.

Entries require positive 5m/1h changes, no greater than 12%/40%, at least half the
24h average hourly volume, and at least half hourly trades being buys. These are
predeclared defensive hypotheses, not optimised or proven indicators. Counts are
not buy/sell dollar volumes. Missing technical fields block entries. No fabricated
RSI, MACD, candles or verified whale ownership is used. Signal AND quote ages are
checked again immediately before entry; slow provider work cannot permit stale buys.
Sells run before buys, so same-cycle closures update cooldowns before allocation.

Bounded free public RSS checks use Solana Status and CoinDesk (two requests, four
seconds each, 256KB limit, once per 15 minutes). Source status, publication dates
and recent relevant headlines are saved. A six-hour relevant adverse headline
blocks new entries; resolved incidents do not trigger that keyword flag. This is
conservative headline classification, not verified event analysis or individual
meme-token news coverage. Both feeds unavailable or context older than 30 minutes
blocks new entries. Partial coverage halves entry sizing and is displayed. Feed
failures never prevent existing position management. No external AI is required.

Positive net token histories earn selection priority using mean net ROI shrunk by
10 pseudo-observations; they do not alone increase exposure. Wallet and feature
reinforcement still require the existing frozen forward OOS evaluation and remain
capped at 1.5%. The new policy uses its own registration time for forward quote
comparisons. Sparse winners cannot bypass negative controls or certification.

The dashboard exposes each pool's policy decision and net history, news coverage,
and forward accepted/blocked quote cohorts. Forward cohorts register before the
entry, use at most one observation per pool/hour, and measure 5/30/60-minute later
sampled returns net of 1% each side. Quotes more than ten minutes late stay missing.
There are no extra market-data requests or backfilled wins. This comparison is
not a portfolio backtest or causal proof; no shadow strategy promotes automatically.
Fewer entries, including periods with none, are expected when evidence is weak.
Rollback code only; never restore an old account snapshot.

Primary GeckoTerminal requests are now spaced at least 2.1 seconds apart, within
a 70-second cycle budget and the original three-attempt ceiling. HTTP 429 is never
retried immediately: a persisted provider-wide cooldown honours Retry-After
(default 60 seconds, maximum one day), also suppressing supplemental Gecko reads
while active. Independent quote-only fallback remains observational. Rate limiting
still reports degraded health; no error is relabelled as a successful market read.
The account and exits remain persistent when a provider cannot supply fresh data.
