# FX Intelligence · Research-only terminal

The previous crypto wallet engine, paper trading workflows and portfolio UI were reset and removed from this branch at the owner's request. The Git history still contains old commits but no old engine files are present in the current tree.

Website: https://rayyansorefan.github.io/standalone-wallet-paper-agent/

The dashboard is a static GitHub Pages site; its initial sanitized docs/fx-feed.json was derived from the private OANDA research repo at 2026-10-21T19:03:51Z. The public site contains no API credentials, account IDs or confidential documents. It polls the published feed every 60 seconds but THIS IS NOT AN AUTOMATIC OANDA COLLECTOR. Automated publishing of new private research into the public repository has not yet been implemented or verified; it requires a secure cross-repository bridge. If the feed is over 70 minutes old, the UI blocks entry advice.

Main ChatGPT research reports are scheduled 07:30, 12:00, 14:00 and 16:30 on weekdays, hourly feedback separately around the clock. They are not GitHub Issues and the webpage itself does not deliver ChatGPT push notifications. No promise of 2–4 actual entries per day or winning results is made. OANDA prices are NOT verified Pepperstone broker executable quotes. The stored browser trade journal is self-reported and private to the local browser, and source data are public sanitized market observations only.

The old five-minute crypto workflow no longer exists in this branch. An external Google Apps Script trigger may still attempt to dispatch the removed workflow; it cannot be disabled from this repository and must be turned off in the Google Apps Script account.

## Research-informed demo trade evidence

The Learning section displays a separate read-only `docs/trade-outcomes.json` ledger (first entries: 23 October 2026). These are manually transcribed from user-supplied Pepperstone **demo** screenshots, not imported or broker-API verified. The **14:34 BST** screenshot shows all three research-informed demo shorts closed, with **£117.24 realised** in total and a **£1,117.24 demo balance**, **£0 floating P&L**, and **zero used margin**. An earlier screenshot showed **£55.90 floating** on the third USD/JPY position at 13:55 BST; that amount was superseded by the final £43.00 realised on that position and is retained solely as historic evidence, never added to realised P&L.

Each entry is labelled `signal_match: PENDING` until an immutable earlier research recommendation can be linked to an actual execution record. These cases are research-influenced per the user but not proof of an approved signal, strategy win rate, or predictive edge. This ledger is intentionally separate from `docs/fx-feed.json` to preserve its strict <950 KB/schema validation and publication workflow. No API keys, trading account IDs, or screenshots are published. Trade values on this public dashboard are visible to anyone with the site URL.

The existing device-local journal remains independent. No automatic strategy reinforcement/parameter adjustment, position execution, or brokerage synchronization is implemented. Outcomes are evidence for future disciplined signal-to-fill reviews.
