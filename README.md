# Standalone Wallet Paper Agent — research prototype v1

**PAPER TRADING ONLY · £2,000 simulated opening balance · zero real orders · no Floot, Bee Bots, wallet private keys, paid AI models, or exchange credentials.**

> **Not live or profitable by assertion.** This code has passed local, mocked regression tests, but the authoring environment does not permit outgoing market-data requests, and the connected GitHub integration lacked `Contents: write` permission. The live GeckoTerminal and Rugcheck APIs, actual scheduled execution, and browser-hosted dashboard have **not** yet been verified. There must be no performance claims until forward observations accumulate.

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
