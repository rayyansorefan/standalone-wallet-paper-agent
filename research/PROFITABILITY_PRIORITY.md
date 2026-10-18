# Latest owner priority — 18 October 2026, 14:58 BST

The owner explicitly prioritizes more net profitable trades than losing trades, starting now. Earlier chat instructions restricting work to engineering are superseded. Profitability is not guaranteed by software changes, activity, stopped trading or dashboard improvements.

## Immediate deployed control

The GBP wallet policy lacks a portfolio-wide loss suspension: wallet/pool controls allow new identities to continue the same losing setup. The recorded matching economic policy at pre-deployment snapshot has 16 closes, two net winners, net -£7.0123 and a terminal streak of 12 losses.

`agent/allocation_guard.py` blocks new GBP admissions AND winner additions after three consecutive net losses among deduplicated, completed, same-policy records. It preserves the original balance, all historical losses and existing holdings. Current holdings continue ordinary observed stops, signal exits and maximum hold; no fake liquidation or guaranteed stop fills. Matching evidence that is malformed blocks admissions until resolved. A latched loss suspension cannot expire, clear after a winner from existing holdings, or vanish after retention/policy renaming.

This is capital preservation, not proof of profitable self-improvement. Do not report zero new trades as a better win rate. Keep scanning and forward research alive. The independent futures account and frozen paired trial retain their existing rules and separate ledgers. This change must not invalidate or restart that trial.

## Accountable next work

1. Verify first independent post-deployment Google execution: guard SUSPENDED, no new GBP buys/additions, existing holdings still monitored, full original histories preserved, active comparison fingerprint/registration unchanged, dashboard and paper jobs successful. A runtime hold alone does not prove trading edge.
2. Prioritize evidence-backed profitable admission/exit alternatives and stable prospective evaluation. Do not spend another cycle of development on cosmetic work while losses/invalidated experiments remain unexplained.
3. Keep the active trial stable. Do not tune it from the same outcomes used to claim success. No repeated resets, deleted losses, duplicate experiments or promotion from a few winners.
4. GBP resumption requires a separately reviewed and explicitly versioned release supported by relevant prospective GBP evidence: net positive after modeled costs, more winners than losers, adequate independent sample/time coverage, robust results excluding best trade/day and comparison with a fixed baseline. USD futures evidence alone cannot certify wallet copying. The existing white-paper thresholds remain necessary review gates, not automatic certification. No timer-based resumption or risk escalation.
5. Use issue #37 and this file for durable handoff. The hourly maintainer is authorized to do the tested work; the owner should not relay reports. Keep the suspended original account distinct from continuing research. If no candidate demonstrates an edge, say so instead of inventing a profitable selector.

No paid services or real trading. Preserve the original £2,000 account identity/history, separate USD account, current safety screens, observed -2% warning/-4.5% stop and six-hour GBP maximum hold. Do not erase or relax the new guard merely to meet an activity target. Any release retains the historical suspension record and discloses its evidence.

## Separately registered post-failure holdout

The first prospective GBP signal cohort is retained unchanged. Its early results
showed no net edge from the original gate, momentum, breakout, high-volume or
buyer-pressure arms. `agent/gbp_holdout_lab.py` therefore registers a new,
post-deployment-only anti-chase holdout without modifying or resetting the first
trial. It tests a fixed all-signal control against three broad low-chase,
tempered-continuation and mature-liquid-pullback admission hypotheses. It reads
the existing immutable signal journal, adds no provider requests and never
places or authorizes a GBP entry.

No candidate can become review-eligible before 100 priced observations across
at least 14 dates and 30 pools. It must have more net winners than losers,
positive quote net after the existing two-sided costs and an additional 2pp
stress, profit factor above one, remain positive without its best observation,
best day and best pool, and beat the fixed all-signal control. Thirty priced
loss-dominated negative observations over at least three dates mark an arm as
persistently negative. Both statuses remain research findings only: automatic
promotion and paper entry are disabled, and GBP suspension remains latched.
