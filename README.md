# FX Intelligence · Research-only terminal

The previous crypto wallet engine, paper trading workflows and portfolio UI were reset and removed from this branch at the owner's request. The Git history still contains old commits but no old engine files are present in the current tree.

Website: https://rayyansorefan.github.io/standalone-wallet-paper-agent/

The dashboard is a static GitHub Pages site; its initial sanitized docs/fx-feed.json was derived from the private OANDA research repo at 2026-10-21T19:03:51Z. The public site contains no API credentials, account IDs or confidential documents. It polls the published feed every 60 seconds but THIS IS NOT AN AUTOMATIC OANDA COLLECTOR. Automated publishing of new private research into the public repository has not yet been implemented or verified; it requires a secure cross-repository bridge. If the feed is over 70 minutes old, the UI blocks entry advice.

Main ChatGPT research reports are scheduled 07:30, 12:00, 14:00 and 16:30 on weekdays, hourly feedback separately around the clock. They are not GitHub Issues and the webpage itself does not deliver ChatGPT push notifications. No promise of 2–4 actual entries per day or winning results is made. OANDA prices are NOT verified Pepperstone broker executable quotes. The stored browser trade journal is self-reported and private to the local browser, and source data are public sanitized market observations only.

The old five-minute crypto workflow no longer exists in this branch. An external Google Apps Script trigger may still attempt to dispatch the removed workflow; it cannot be disabled from this repository and must be turned off in the Google Apps Script account.

## Research-informed demo trade evidence

The Learning section displays a separate read-only `docs/trade-outcomes.json` evidence ledger. As of **26 October 2026, 13:58 UK**, five screenshot-supported Pepperstone spread-bet/demo positions are closed at a combined **+£134.19 realised**. The most recent is **GBP/USD short 1.33524 → 1.33345, £0.50 per point, +£8.95 net**, opened 12:31:57 and closed 13:58:11, with **£0.00 commission and £0.00 swap**. Earlier entries and their provenance are retained individually; the ledger has no brokerage API integration.

All five `signal_match` statuses remain `PENDING` unless an immutable earlier recommendation, exact trigger, and execution chronology can be independently reconciled. The 26 October GBP/USD entry differs from the corresponding 12:00 plan (1.33524 actual versus 1.33555 planned); this is useful research-influenced execution evidence, **not** a confirmed simulator fill or formally validated research-entry win. The account snapshot in the file is a historical 23 October record, not the current balance. The separately observed AUD/NZD open trade is not in realised P/L.

The public dashboard displays only sanitized amounts and trade details (no account IDs, credentials or personal documents). It is visible to anyone with the Pages URL. The independent browser-local journal is not proof of broker outcomes.

The private `oanda-fx-research` repository contains a separate set of these screenshot observations for execution review. Strategy-priority adjustments are based on strictly evaluated OANDA bid/ask **paper** outcomes, with conservative minimum sample requirements; screenshots with unverified signal linkage never automatically change weights or entry approvals. OANDA quotes remain distinct from executable Pepperstone prices.
