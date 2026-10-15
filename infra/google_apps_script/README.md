# Private five-minute paper scheduler

This is an infrastructure fallback for the existing paper agent, not a new
trading engine. It does not modify strategy rules, holdings or opening capital.

The owner's private Apps Script project is **Standalone Paper Scheduler**:
https://script.google.com/home/projects/1nvXOSt76K7eok7i3hZEnt8Z3SbmIwRvEyQTe-lNBTxmWwSDKUHkWp7nb/edit

## Operation and verification

- `installScheduler` installs one `paperTick` time-driven trigger every five
  minutes. It is idempotent and does not run a paper-trading cycle itself.
- `paperTick` rejects manual calls without a real trigger event. It reads the
  existing public paper state and dispatches `paper.yml` only when an observation
  has not been persisted in the preceding four minutes.
- The GitHub workflow serializes writers, checks out current `main`, and applies
  a second persisted interval/clock-slot guard in `agent/scheduled.py`. Duplicate
  requests do not produce additional market observations or state commits.
- The same existing market-data, position-monitoring, risk-screening, state-save
  and Pages-publishing pipeline processes each accepted clock event.
- GitHub calls the external event `workflow_dispatch`. Proof that it was
  automatic requires the Google execution's **Time-driven** type and its log,
  matched to the GitHub event inputs and persisted `execution` provenance.
  A manually clicked GitHub run is not evidence of independent scheduling.
- Native GitHub cron remains enabled as a second source. Its activation alone
  does not prove that GitHub's scheduler has produced an event.

## Credentials and cost

`GITHUB_ACTIONS_TOKEN` is stored in the private project's Script Properties,
never in this repository, log messages or dashboard. It is restricted to Actions
read/write plus required Metadata read access for this repository only. No other
repositories, contents-write or account permissions were granted.

**The initial short-lived token expires on 15 November 2026 according to GitHub's
creation confirmation.** Rotate it before expiry in the private Script
Properties; do not add the token to this file or any source file.

No paid plan, paid API or billing upgrade is required or configured. Apps Script
consumer quotas and provider delays still apply. A five-minute trigger is a
target interval, not a hard real-time guarantee. GitHub runner and publication
delays are additional to timer latency.

Provider documentation:
- https://developers.google.com/apps-script/reference/script/clock-trigger-builder#everyMinutes(Integer)
- https://developers.google.com/apps-script/guides/services/quotas

Run scheduler regression tests with:

```sh
node --test infra/google_apps_script/test.mjs
python -m unittest discover -s tests -v
```
