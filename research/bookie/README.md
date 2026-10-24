# Bookie Intelligence Hub

Live dashboard: https://rayyansorefan.github.io/standalone-wallet-paper-agent/bookie/

This independent sports research page preserves the FX homepage. It never logs in to bet365 or places bets. Personal betting entries are stored only in the browser.

## Four-hour workflow

Workflow file: .github/workflows/bookie-research.yml
UTC schedule: 00:17, 04:17, 08:17, 12:17, 16:17, 20:17. GitHub cron is best-effort, not a timing guarantee. Each cycle runs tests, collects prices, commits its sanitized feed, dispatches GitHub Pages and verifies the published feed matches the expected snapshot. Do not treat an old snapshot as current.

## Connect live bet365-labelled research data

Create a free API key through https://oddspapi.io/. Published free plan: 250 requests/month. The source includes bet365 and other bookmakers.

In GitHub repository rayyansorefan/standalone-wallet-paper-agent open Settings > Secrets and variables > Actions > New repository secret.

Secret name: ODDSPAPI_API_KEY

Paste the key into GitHub, never the public repository or this chat. Then manually dispatch the sports workflow or let the next four-hour trigger run. Until connected, the dashboard honestly displays NOT CONFIGURED and NO BET.

The free adapter budgets up to 220 calls/month: roughly one cross-book fixture board per four-hour cycle, daily fixture discovery and limited completed-result checks. It does NOT cover every sports event or every bet365 market. For broader coverage the underlying source would need more provider quota; no subscription is activated by this project.

Alternative: ODDS_API_KEY for The Odds API v4, with source sports adjustable by the BOOKIE_SPORT_KEYS Actions repository variable. Its documented UK feed excludes bet365 so it can provide reference signals, not verified bet365 approvals.

## Learning and guardrails

Forecasts are recorded BEFORE kick-off with a timestamp, original no-vig consensus probability, adjustment, quoted odds and rejection/approval reason. Results are graded only after confirmed settlement. Missing or ambiguous outcomes stay pending.

Learning is real but cautious: calibrations are calculated per sport and probability band from resolved historical forecasts, using an 80-observation shrinkage prior. Minimum 40 graded observations before any change, cap on adjustments of +/- 4 percentage points. Every frozen adjusted forecast is compared prospectively with the original baseline using Brier scores; repeated underperformance automatically pauses further adjustments.

Both accepted and rejected/watch predictions are scored, including the losing misses. Selecting winners with hindsight is not learning. Model backtesting never implies a guaranteed profit.

A BET_CANDIDATE requires a quote from bet365 in the licensed feed no more than 30 minutes old; at least 3 distinct comparator bookmaker price vectors; conservative estimated win probability above 52%; conservative expected return above 2%; and actual odds above the model minimum. The software publishes no more than three and refuses to fabricate a recommendation when any condition fails.

The odds are provider-labelled prices, not authenticated offers in the user's app. No raw credentials, account access, auto-execution, scraping, or user financial data are written to GitHub. No ChatGPT push notifications are scheduled here.

## Status

A live research pipeline has been deployed and tested. Live bet365 data collection remains UNCONFIGURED until the owner adds the licensed data key. The first runs successfully published this honest no-data state. The model has no established profitable performance record.
