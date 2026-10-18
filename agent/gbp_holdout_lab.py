"""Post-failure GBP admission holdout. Research only; never places orders.

The first GBP signal trial showed that stronger short-term momentum, volume pace
and buyer counts did not create a net edge. This separately registered holdout
tests broad anti-chase hypotheses only on signals observed after registration.
It reads the immutable upstream evidence journal and cannot reset either trial.
"""
import datetime as dt
import hashlib
import json
import math

KEY = "gbp_holdout_lab_v1"
VERSION = "GBP_ANTI_CHASE_HOLDOUT_1"
UPSTREAM_KEY = "gbp_signal_lab_v1"
HORIZONS = ("5m", "30m", "60m")
MIN_REJECT_PRICED = 30
MIN_REJECT_DAYS = 3
MIN_REVIEW_PRICED = 100
MIN_REVIEW_DAYS = 14
MIN_REVIEW_POOLS = 30
RULES = {
    "all_fresh_signals_control": "all complete post-registration wallet signals",
    "tempered_continuation": (
        "liquidity>=100k, age>=6h, m5 -0.5..1%, h1 1..10%, "
        "volume pace 0.4..1.2, buyers 45..58%"),
    "mature_liquid_pullback": (
        "liquidity>=250k, age>=24h, m5 -3..0%, h1 0..12%, "
        "volume pace 0.2..1.2, buyers 40..58%"),
    "policy_low_chase": (
        "original gate plus liquidity>=100k, age>=6h, m5 -1..1%, h1 0..12%, "
        "volume pace 0.2..1.2, buyers 40..58%"),
}
FINGERPRINT = hashlib.sha256(json.dumps([
    VERSION, RULES, HORIZONS,
    "post_registration_only", "immutable_upstream_journal",
    "1pct_each_side_net_quote", "additional_2pp_stress",
    MIN_REJECT_PRICED, MIN_REJECT_DAYS,
    MIN_REVIEW_PRICED, MIN_REVIEW_DAYS, MIN_REVIEW_POOLS,
    "majority_wins_positive_net_profit_factor",
    "positive_without_best_observation_day_pool",
    "better_mean_than_fixed_all_signal_control", "no_auto_promotion",
], sort_keys=True).encode()).hexdigest()


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def match(arm, row):
    features = row.get("signal_technical")
    if not isinstance(features, dict):
        return None
    values = [finite(features.get(key)) for key in (
        "change_5m_pct", "change_1h_pct", "volume_pace_ratio",
        "buy_count_share", "liquidity_usd", "age_hours")]
    if any(value is None for value in values):
        return None
    m5, h1, pace, buyers, liquidity, age = values
    if arm == "all_fresh_signals_control":
        return True
    common = liquidity >= 100000 and age >= 6
    if arm == "tempered_continuation":
        return (common and -.5 <= m5 <= 1 and 1 <= h1 <= 10 and
                .4 <= pace <= 1.2 and .45 <= buyers <= .58)
    if arm == "mature_liquid_pullback":
        return (liquidity >= 250000 and age >= 24 and -3 <= m5 <= 0 and
                0 <= h1 <= 12 and .2 <= pace <= 1.2 and
                .4 <= buyers <= .58)
    if arm == "policy_low_chase":
        return (row.get("accepted_by_policy") is True and common and
                -1 <= m5 <= 1 and 0 <= h1 <= 12 and .2 <= pace <= 1.2 and
                .4 <= buyers <= .58)
    raise ValueError("Unknown holdout arm")


def _drawdown(values):
    running = peak = worst = 0.
    for value in values:
        running += value
        peak = max(peak, running)
        worst = max(worst, peak - running)
    return worst


def _score(rows, horizon, control_mean=None, comparator=False):
    priced = []
    missing = pending = 0
    for row in rows:
        outcome = (row.get("outcomes") or {}).get(horizon)
        if outcome is None:
            pending += 1
            continue
        value = finite(outcome.get("net_quote_roi_pct")) if isinstance(outcome, dict) else None
        if value is None:
            missing += 1
        else:
            priced.append((row, value))
    values = [value for _, value in priced]
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    net = sum(values)
    positive = sum(value for value in values if value > 0)
    negative = -sum(value for value in values if value < 0)
    days = {}
    pools = {}
    for row, value in priced:
        day = str(row.get("at", ""))[:10]
        days[day] = days.get(day, 0.) + value
        pool = row.get("token")
        if pool:
            pools[pool] = pools.get(pool, 0.) + value
    best = max(values, default=0.)
    best_day = max(days.values(), default=0.)
    best_pool = max(pools.values(), default=0.)
    count = len(values)
    mean = net / count if count else None
    stress = net - 2 * count
    advantage = (mean - control_mean if mean is not None and control_mean is not None
                 else None)
    sufficient = (count >= MIN_REVIEW_PRICED and len(days) >= MIN_REVIEW_DAYS and
                  len(pools) >= MIN_REVIEW_POOLS and missing == 0 and pending == 0)
    robust = bool(sufficient and wins > losses and net > 0 and stress > 0 and
                  positive > negative and net - best > 0 and net - best_day > 0 and
                  net - best_pool > 0 and advantage is not None and advantage > 0)
    rejected = bool(count >= MIN_REJECT_PRICED and len(days) >= MIN_REJECT_DAYS and
                    wins <= losses and net < 0 and stress < 0)
    status = ("COMPARATOR_ONLY" if comparator else
              "REVIEW_ELIGIBLE_NOT_PROMOTED" if robust else
              "REJECTED_PERSISTENT_NEGATIVE" if rejected else
              "NOT_ROBUST" if sufficient else "COLLECTING")
    return {
        "selected": len(rows), "priced": count, "missing": missing,
        "pending": pending, "wins": wins, "losses": losses,
        "win_rate_pct": round(100 * wins / count, 2) if count else None,
        "net_quote_roi_points": round(net, 4) if count else None,
        "mean_net_quote_roi_pct": round(mean, 4) if mean is not None else None,
        "stressed_net_roi_points": round(stress, 4) if count else None,
        "profit_factor": round(positive / negative, 3) if negative else
                         (None if not positive else "INF"),
        "max_cumulative_drawdown_points": round(_drawdown(values), 4) if count else None,
        "net_without_best_observation": round(net - best, 4) if count else None,
        "net_without_best_day": round(net - best_day, 4) if count else None,
        "net_without_best_pool": round(net - best_pool, 4) if count else None,
        "distinct_entry_days": len(days), "distinct_pools": len(pools),
        "mean_advantage_vs_control_pp": round(advantage, 4) if advantage is not None else None,
        "review_status": status, "paper_entry_enabled": False,
    }


def update(state, now):
    if now.tzinfo is None:
        raise ValueError("UTC-aware now required")
    research = state.setdefault("research", {})
    book = research.setdefault(KEY, {
        "version": VERSION, "registered_at": now.isoformat(),
        "hypothesis_sha256": FINGERPRINT, "cycles": 0,
        "status": "COLLECTING_UNPROVEN", "automatic_promotion": False,
        "paper_entries_allowed": False, "candidate_rules": dict(RULES),
    })
    if book.get("version") != VERSION or book.get("hypothesis_sha256") != FINGERPRINT:
        book["status"] = "INVALIDATED_SOURCE_CHANGED"
        book["automatic_promotion"] = False
        book["paper_entries_allowed"] = False
        return book
    upstream = research.get(UPSTREAM_KEY) or {}
    if upstream.get("retention_overflow") or upstream.get("retention_conflict"):
        book["status"] = "UPSTREAM_EVIDENCE_UNSAFE"
        return book
    start = dt.datetime.fromisoformat(str(book["registered_at"]).replace("Z", "+00:00"))
    if start.tzinfo is None:
        book["status"] = "INVALID_REGISTRATION"
        return book
    rows = []
    for row in (upstream.get("retained_forward_signals") or {}).values():
        if not isinstance(row, dict):
            continue
        try:
            at = dt.datetime.fromisoformat(str(row.get("at", "")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if at.tzinfo is not None and at >= start:
            rows.append(row)
    rows.sort(key=lambda row: (row.get("at") or "", row.get("signal_id") or ""))
    matches = {arm: [row for row in rows if match(arm, row) is True] for arm in RULES}
    control = {horizon: _score(matches["all_fresh_signals_control"], horizon,
                               comparator=True)
               for horizon in HORIZONS}
    reports = {"all_fresh_signals_control": {"horizons": control}}
    for arm in RULES:
        if arm == "all_fresh_signals_control":
            continue
        reports[arm] = {"horizons": {
            horizon: _score(matches[arm], horizon,
                            control[horizon]["mean_net_quote_roi_pct"])
            for horizon in HORIZONS}}
    statuses = [score["review_status"] for arm in reports.values()
                for score in arm["horizons"].values()]
    candidate_arms = [arm for arm in reports if arm != "all_fresh_signals_control"]
    book.update(
        last_run=now.isoformat(), cycles=book.get("cycles", 0) + 1,
        post_registration_observations=len(rows), reports=reports,
        status=("REVIEW_CANDIDATE_EXISTS" if "REVIEW_ELIGIBLE_NOT_PROMOTED" in statuses
                else "CANDIDATES_REJECTED" if any(
                    all(score["review_status"] == "REJECTED_PERSISTENT_NEGATIVE"
                        for score in reports[arm]["horizons"].values())
                    for arm in candidate_arms)
                else "COLLECTING_UNPROVEN"),
        automatic_promotion=False, paper_entries_allowed=False,
        evidence_note=(
            "Separate post-registration holdout; quote returns are not fills. "
            "Review requires 100 priced outcomes across 14 days/30 pools, majority "
            "wins, positive extra-stressed net result, profit factor above one, "
            "positive result without the best observation/day/pool and improvement "
            "over the fixed all-signal control. No automatic GBP resumption."))
    return book


def safe_update(state, now):
    try:
        return update(state, now)
    except Exception as exc:
        book = state.setdefault("research", {}).setdefault(KEY, {})
        book.update(status="RESEARCH_ERROR", error_type=type(exc).__name__,
                    automatic_promotion=False, paper_entries_allowed=False)
        return book
