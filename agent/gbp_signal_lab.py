"""Prospective, quote-only GBP strategy hypotheses. Never trades, sizes, or resumes GBP.

All filters are predeclared; signal features are frozen BEFORE future quote marks.
No extra API calls. Results are candidate diagnostics, not executable trade P&L.
"""
import datetime as dt
import hashlib
import json
import math
from .policy_evidence import certifiable_trade

KEY = 'gbp_signal_lab_v1'
VERSION = 'GBP_PROSPECTIVE_SIGNAL_LAB_1'
HORIZONS = ('5m', '30m', '60m')
# Fixed before prospective observations. No post-hoc threshold optimisation.
# These are long-SPOT hypotheses; short/fade requires executable futures data.
ARMS = {
    'observed_original_gate': 'policy',
    'moderate_momentum': 'moderate',
    'accelerating_breakout': 'breakout',
    'high_volume_trend': 'trend',
    'buyer_pressure': 'buyers',
    'liquid_confirmed_trend': 'liquid',
}
FINGERPRINT = hashlib.sha256(json.dumps(
    [VERSION, ARMS, HORIZONS, '1pct_each_side_net_quotes',
     'additional_1pct_each_side_stress', 'no_auto_promotion'],
    sort_keys=True).encode()).hexdigest()


def finite(x):
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError, OverflowError):
        return None


def match(arm, item):
    f = item.get('signal_technical')
    if not isinstance(f, dict):
        return None  # Missing pre-observation features: no retrospective repair.
    keys = ('change_5m_pct', 'change_1h_pct', 'volume_pace_ratio',
            'buy_count_share')
    vals = [finite(f.get(k)) for k in keys]
    if any(v is None for v in vals):
        return None
    m5, h1, pace, buyers = vals
    if arm == 'observed_original_gate':
        return item.get('accepted_by_policy') is True
    if arm == 'moderate_momentum':
        return .3 <= m5 <= 2 and 1 <= h1 <= 8 and pace >= .7 and buyers >= .55
    if arm == 'accelerating_breakout':
        return 1 <= m5 <= 4 and 4 <= h1 <= 16 and pace >= 1 and buyers >= .55
    if arm == 'high_volume_trend':
        return 2 <= m5 <= 8 and 8 <= h1 <= 25 and pace >= 1.3 and buyers >= .55
    if arm == 'buyer_pressure':
        return 0 < m5 <= 8 and 0 < h1 <= 25 and pace >= .8 and buyers >= .6
    if arm == 'liquid_confirmed_trend':
        liquidity = finite(f.get('liquidity_usd'))
        age = finite(f.get('age_hours'))
        return (liquidity is not None and age is not None and
                liquidity >= 250000 and age >= 24 and .5 <= m5 <= 4
                and 2 <= h1 <= 15 and pace >= 1 and buyers >= .55)
    raise ValueError('Unknown fixed hypothesis')


def recent_winner_audit(closed):
    rows = [r for r in closed if isinstance(r, dict) and finite(r.get('net_pnl_gbp')) is not None]
    wins = sorted((r for r in rows if r['net_pnl_gbp'] > 0),
                  key=lambda r: (r.get('exit_at') or '', r.get('signal_id') or ''))
    selected = wins[-11:]
    losses = [r for r in rows if r['net_pnl_gbp'] < 0]
    current = [r for r in rows if certifiable_trade(r)]
    current_wins = [r for r in current if r['net_pnl_gbp'] > 0]
    return {
        'closed': len(rows), 'wins': len(wins), 'losses': len(losses),
        'last_winners_sample': len(selected),
        'last_winners_net_gbp': round(sum(r['net_pnl_gbp'] for r in selected), 4),
        'last_winners_distinct_pools': len({r.get('mint') or r.get('token') for r in selected}),
        'last_winners_technical_snapshots': sum(
            isinstance((r.get('entry_assessment') or {}).get('technical'), dict)
            for r in selected),
        'last_winners_current_policy': sum(certifiable_trade(r) for r in selected),
        'current_policy_closed': len(current),
        'current_policy_wins': len(current_wins),
        'current_policy_loss_count': sum(r['net_pnl_gbp'] < 0 for r in current),
        'current_policy_net_gbp': round(sum(r['net_pnl_gbp'] for r in current), 4),
        'all_time_net_gbp': round(sum(r['net_pnl_gbp'] for r in rows), 4),
        'interpretation': 'Descriptive only. Legacy winners are non-comparable across changed exits.'
    }


def _score(items, horizon):
    selected = len(items)
    priced = []
    missing = 0
    pending = 0
    for x in items:
        outcome = (x.get('outcomes') or {}).get(horizon)
        if outcome is None:
            pending += 1
        elif not isinstance(outcome, dict) or finite(outcome.get('net_quote_roi_pct')) is None:
            missing += 1
        else:
            priced.append((x, float(outcome['net_quote_roi_pct'])))
    vals = [v for _, v in priced]
    dates = {str(x.get('at',''))[:10] for x, _ in priced}
    pools = {x.get('token') for x, _ in priced if x.get('token')}
    wins = sum(v > 0 for v in vals)
    # Quote outcome already models 1% on entry AND exit; conservative
    # additional 2 percentage points are a *stress*, not an executed fill.
    stress = [v - 2 for v in vals]
    sum_net = sum(vals)
    return {
        'selected': selected, 'priced': len(vals), 'missing': missing, 'pending': pending,
        'wins': wins, 'losses': sum(v < 0 for v in vals),
        'win_rate_pct': round(100*wins/len(vals),2) if vals else None,
        'mean_net_quote_roi_pct': round(sum_net/len(vals),4) if vals else None,
        'mean_stressed_quote_roi_pct': round(sum(stress)/len(stress),4) if vals else None,
        'distinct_entry_days': len(dates), 'distinct_pools': len(pools),
        'complete_outcomes': bool(vals) and not missing and not pending,
        # Repeated pools/cycles are NOT independent observations; review
        # would require day/pool clustering and genuinely fresh holdout.
        'evidence_sufficient_for_review': False,
        'paper_entry_enabled': False,
    }


def update(state, now):
    r = state.setdefault('research', {})
    book = r.setdefault(KEY, {
        'version': VERSION, 'registered_at': now.isoformat(),
        'hypothesis_sha256': FINGERPRINT, 'cycles': 0,
        'status': 'COLLECTING_UNPROVEN', 'automatic_promotion': False,
        'scope': 'SPOT_LONG_QUOTES_ONLY_NO_REAL_OR_GBP_ORDERS',
        'candidate_families': dict(ARMS),
    })
    book['historical_audit'] = recent_winner_audit(state.get('closed') or [])
    if book.get('hypothesis_sha256') != FINGERPRINT or book.get('version') != VERSION:
        book['status'] = 'INVALIDATED_RESEARCH_CODE_CHANGED'
        book['automatic_promotion'] = False
        return book
    d = r.get('decision_v1') or {}
    start = dt.datetime.fromisoformat(book['registered_at'].replace('Z','+00:00'))
    if start.tzinfo is None:
        book['status'] = 'INVALID_REGISTRATION'
        return book
    allrows = (d.get('forward_outcomes') or []) + (d.get('forward_pending') or [])
    # decision_v1 retains only its last 500 completed signals. Without this
    # independent evidence journal, losing outcomes vanish from the denominator
    # as the main engine continues running; a prospective winner comparison
    # would eventually become unknowingly biased.
    retained = book.setdefault('retained_forward_signals', {})
    excluded = 0
    for row in allrows:
        if not isinstance(row, dict) or not row.get('signal_id'):
            excluded += 1
            continue
        try:
            at = dt.datetime.fromisoformat(str(row['at']).replace('Z','+00:00'))
        except (ValueError, TypeError, KeyError):
            excluded += 1
            continue
        if at.tzinfo is None or at < start or not isinstance(row.get('signal_technical'),dict):
            excluded += 1
            continue
        identity = hashlib.sha256(str(row['signal_id']).encode('utf8')).hexdigest()
        if identity not in retained:
            if len(retained) >= 20000:
                book['retention_overflow'] = True
                continue  # Visible research failure; never claim certified evidence.
            retained[identity] = dict(
                signal_id=identity,
                token=hashlib.sha256(str(row.get('token','')).encode('utf8')).hexdigest(),
                at=at.isoformat(),
                accepted_by_policy=row.get('accepted_by_policy') is True,
                signal_technical={
                    k: finite((row.get('signal_technical') or {}).get(k))
                    for k in ('change_5m_pct','change_1h_pct','volume_pace_ratio',
                              'buy_count_share','liquidity_usd','age_hours',
                              'signal_age_seconds')
                },
                outcomes={})
        evidence = retained[identity]
        if evidence['at'] != at.isoformat():
            book['retention_conflict'] = True
            continue
        # Evidence at entry is immutable. Only append newly mature, forward
        # outcomes; never revise or erase priced losses based on newer marks.
        for horizon in HORIZONS:
            outcome = (row.get('outcomes') or {}).get(horizon)
            if horizon in evidence['outcomes'] or not isinstance(outcome, dict):
                continue
            value = finite(outcome.get('net_quote_roi_pct'))
            if value is not None:
                evidence['outcomes'][horizon] = {'net_quote_roi_pct': value}
            elif outcome.get('status') == 'MISSING_FRESH_QUOTE':
                evidence['outcomes'][horizon] = {'status': 'MISSING_FRESH_QUOTE'}
    observations = list(retained.values())
    reports = {}
    for arm in ARMS:
        matched = [match(arm, row) for row in observations]
        accepted = [row for row, yes in zip(observations, matched) if yes is True]
        reports[arm] = {
            'feature_complete': sum(yes is not None for yes in matched),
            'selected': len(accepted),
            'horizons': {h: _score(accepted,h) for h in HORIZONS}
        }
    book.update(last_run=now.isoformat(), cycles=book.get('cycles',0)+1,
                observations=len(observations), excluded_historical_or_unfeatured=excluded,
                reports=reports,
                retained_forward_signal_count=len(retained),
                status=('EVIDENCE_RETENTION_UNSAFE'
                        if book.get('retention_overflow') or book.get('retention_conflict')
                        else 'COLLECTING_UNPROVEN'),
                warning='Signal-time registered quote comparison only, no actual fills; '
                        'historical pattern mining cannot validate this strategy. '
                        '100+ prospective independent trades across >=14 dates, '
                        'closed net economics, cost stress and clustered holdout '
                        'are required before separate review; no automatic promotion.')
    return book


def safe_update(state, now):
    try:
        return update(state, now)
    except Exception as exc:
        # Lab must not break an unattended account cycle or leak private details.
        b = state.setdefault('research',{}).setdefault(KEY,{})
        b.update(status='RESEARCH_ERROR',error_type=type(exc).__name__,
                 automatic_promotion=False)
        return b
