"""Frozen, cost-aware GBP winner-trait *research*, never an allocation permission.

This is a deliberately conservative hypothesis distilled from eleven historical
winning closes. Their repeated tokens and mixed exit regimes make it unproven.
No API calls, paper entries, account changes or strategy promotion are allowed.
"""
import hashlib
import math
from pathlib import Path

VERSION = "GBP_WINNER_TRAITS_FORWARD_V1"
# Predeclared at registration. Do not retrospectively optimize after outcomes.
LIQUIDITY_USD = 250_000
POOL_AGE_HOURS = 24
MIN_M5_PCT = .5
MIN_H1_PCT = 4.
MIN_VOLUME_PACE = .65
MIN_BUY_SHARE = .50
MAX_BUY_SHARE = .60


def source_hash():
    here = Path(__file__).parent
    return hashlib.sha256(b''.join(
        (here / name).read_bytes() for name in ('winner_traits.py', 'decision.py')
    )).hexdigest()


def number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def classify(pool, assessment):
    """Return positive selection only for complete, independently gated inputs.

    The core caller has already verified Rugcheck and fetched the actual swap
    feed before producing a forward-observed signal. This must never be used
    to bypass either original entry or security gates.
    """
    if not isinstance(assessment, dict) or assessment.get('allowed') is not True:
        return False
    t = assessment.get('technical') or {}
    if not isinstance(t, dict) or not isinstance(pool, dict):
        return False
    values = [number(pool.get(k)) for k in ('liquidity_usd', 'age_hours')]
    values += [number(t.get(k)) for k in
               ('change_5m_pct', 'change_1h_pct',
                'volume_pace_ratio', 'buy_count_share')]
    if any(x is None for x in values):
        return False
    liquidity, age, m5, h1, pace, buy_share = values
    return (liquidity >= LIQUIDITY_USD and age >= POOL_AGE_HOURS
            and MIN_M5_PCT <= m5 <= 12 and MIN_H1_PCT <= h1 <= 40
            and pace >= MIN_VOLUME_PACE
            and MIN_BUY_SHARE <= buy_share <= MAX_BUY_SHARE)


def forward_metrics(observations, *, selected):
    """Only post-registration, labelled observations; missing quotes not wins."""
    cohort = [x for x in observations if x.get('winner_traits_v1') is selected]
    result = {'observations': len(cohort),
              'distinct_signal_days': len({x.get('at', '')[:10] for x in cohort}),
              'distinct_pools': len({x.get('token') for x in cohort}),
              'horizons': {}}
    for minute in (5, 30, 60):
        key = str(minute) + 'm'
        available = []
        missing = pending = 0
        for x in cohort:
            sample = x.get('outcomes', {}).get(key)
            if sample is None:
                pending += 1
            elif isinstance(sample, dict):
                ret = number(sample.get('net_quote_roi_pct'))
                if ret is None:
                    missing += 1
                else:
                    available.append(ret)
            else:
                missing += 1
        result['horizons'][key] = {
            'priced': len(available), 'missing': missing, 'pending': pending,
            'net_positive': sum(x > 0 for x in available),
            'net_negative_or_zero': sum(x <= 0 for x in available),
            'mean_net_quote_roi_pct':
                round(sum(available) / len(available), 4) if available else None,
        }
    return result


def forward_report(observations, registered_at):
    # Stop any retrofit of existing observation cohorts.
    fresh = [x for x in observations
             if x.get('winner_traits_version') == VERSION
             and x.get('at', '') >= registered_at]
    chosen = forward_metrics(fresh, selected=True)
    control = forward_metrics(fresh, selected=False)
    return {
        'version': VERSION, 'registered_at': registered_at,
        'chosen': chosen, 'other_eligible_signals': control,
        'automatic_promotion': False, 'status': 'UNPROVEN',
        'note': ('Fresh quoted 5/30/60m outcomes net of modeled 1pct each side; '
                 'not realised positions, full 6h exit simulation, independent '
                 'trades or proof of profitability. Insufficient or missing '
                 'observations never count as success.'),
    }
