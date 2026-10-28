# FX Intelligence · Research-only terminal

The previous crypto wallet engine, paper trading workflows and portfolio UI were reset and removed from this branch at the owner's request. The Git history still contains old commits but no old engine files are present in the current tree.

Website: https://rayyansorefan.github.io/standalone-wallet-paper-agent/

The dashboard is a static GitHub Pages site; its initial sanitized docs/fx-feed.json was derived from the private OANDA research repo at 2026-10-21T19:03:51Z. The public site contains no API credentials, account IDs or confidential documents. It polls the published feed every 60 seconds but THIS IS NOT AN AUTOMATIC OANDA COLLECTOR. Automated publishing of new private research into the public repository has not yet been implemented or verified; it requires a secure cross-repository bridge. If the feed is over 70 minutes old, the UI blocks entry advice.

Main ChatGPT research reports are scheduled 07:30, 12:00, 14:00 and 16:30 on weekdays, hourly feedback separately around the clock. They are not GitHub Issues and the webpage itself does not deliver ChatGPT push notifications. No promise of 2–4 actual entries per day or winning results is made. OANDA prices are NOT verified Pepperstone broker executable quotes. The stored browser trade journal is self-reported and private to the local browser, and source data are public sanitized market observations only.

The old five-minute crypto workflow no longer exists in this branch. An external Google Apps Script trigger may still attempt to dispatch the removed workflow; it cannot be disabled from this repository and must be turned off in the Google Apps Script account.

## Research-informed demo trade evidence

The Learning / My results section reads `docs/trade-outcomes.json`, a separate, screenshot-sourced Pepperstone demo ledger. As of **28 October 2026, 09:10:52 UK**, there are **nine closed positions: seven gains, two losses, and +£153.50 realised cumulative P/L**. Today has two confirmed closures: **NZD/JPY SHORT +£22.90** at 08:11:36 and **GBP/USD SHORT −£5.61 (stop loss)** at 09:10:52, **+£17.29 combined**. The earlier 08:22 snapshot showed **NZD/CAD +£4.92** and **NZD/SGD +£7.44** floating. A later 11:22 screenshot shows the Pepperstone **Demo #1 bank at £1,174.53 with zero open orders or positions**. This confirms both earlier positions were no longer open but does not reveal their exact closing P/L; do not convert floating snapshots into realised results.

The GBP/USD short at 1.32920 was closed at 1.32971, £1.10 per point, by the broker stop. Its £5.61 loss was approximately **0.48% of previously reported £1,174.10 equity**, exceeding the research protocol's **0.25% per-trade guideline**. It was a discretionary execution before completed bearish M15 confirmation, not a formally approved entry. Preserve that loss and the earlier AUD/NZD stop-out in the strategy history.

Positive screenshot-backed trades queue **prospective pattern-review hypotheses**; adverse results queue confirmation, position-sizing and stop-risk checks. The dashboard displays both without granting entry permission. All `signal_match` values remain `PENDING` until original frozen signal, trigger timing, broker spread/fill and costs are independently reconciled. Broker screenshots are not OANDA simulated fills and **do not adjust strategy weights**, which require robust forward paper evidence after costs. Unfilled and expired candidates must be included in comparisons, not just executed winners.

Public data contain sanitized trade amounts and no brokerage account identifiers, credentials or private documents. This website is public at https://rayyansorefan.github.io/standalone-wallet-paper-agent/; it has no Pepperstone API connection. The latest 11:22 account-card figure is evidenced; individual closing execution and realised P/L for the earlier NZD/CAD and NZD/SGD positions remain unverified.
