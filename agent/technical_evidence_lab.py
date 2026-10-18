"""Frozen, isolated TA evidence matrix using EXISTING five-minute DEX pool marks.

Never controls entries, exits, sizing, futures, existing lab or account state.
Screens must be PASS for admission to the simulated study; missing/stale marks
never become zero returns. No additional API requests or imagined fills.
"""
import datetime as dt
import hashlib
import json
import math
import statistics

KEY = 'technical_evidence_lab_v1'
VERSION = 'GBP_TA_FORWARD_QUOTES_1'
HORIZONS = (5, 30, 60)
ARMS = ('existing_technical_gate', 'ema_rsi_macd_trend',
        'macd_confirmed_breakout', 'ema_pullback_reclaim',
        'avoid_overheated_momentum')
SPEC = {
    'version': VERSION, 'arms': ARMS, 'horizons_minutes': HORIZONS,
    'min_marks': 35, 'max_gap_seconds': 660,
    'fees_each_side_pct': 1., 'additional_stress_pct': 2.,
    'min_liquidity_usd': 250000, 'min_pool_age_hours': 24,
    'candidate_safety': 'CURRENT_CYCLE_PASS_ONLY',
    'no_auto_promotion': True,
}
FINGERPRINT = hashlib.sha256(json.dumps(SPEC, sort_keys=True).encode()).hexdigest()
UTC = dt.timezone.utc


def number(value):
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError, OverflowError):
        return None


def timestamp(value):
    try:
        out = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return out.astimezone(UTC) if out.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def price_marks(rows, now):
    """Bounded ordered historical marks only, no future samples/lookahead."""
    grouped = {}
    for row in rows[-4000:]:
        if not isinstance(row, dict) or not row.get('pool'):
            continue
        at = timestamp(row.get('at'))
        price = number(row.get('price_usd'))
        if (at is None or price is None or price <= 0 or
                not dt.timedelta(0) <= now-at <= dt.timedelta(hours=4)):
            continue
        grouped.setdefault(str(row['pool']), {})[at] = (price, row)
    return {pool: [(t, *points[t]) for t in sorted(points)]
            for pool, points in grouped.items()}


def ema(values, period):
    weight = 2 / (period+1)
    result = []
    value = values[0]
    for x in values:
        value = weight*x+(1-weight)*value
        result.append(value)
    return result


def indicators(marks, now):
    if len(marks) < 35 or now-marks[-1][0] > dt.timedelta(minutes=10):
        return None
    recent = marks[-35:]
    if any(not 0 < (b[0]-a[0]).total_seconds() <= SPEC['max_gap_seconds']
           for a, b in zip(recent, recent[1:])):
        return None
    values = [p for _, p, _ in recent]
    gains = [max(0, values[i]-values[i-1]) for i in range(-14, 0)]
    losses = [max(0, values[i-1]-values[i]) for i in range(-14, 0)]
    total = sum(gains)+sum(losses)
    rsi = 50 if total == 0 else 100*sum(gains)/total
    e12, e26 = ema(values, 12), ema(values, 26)
    macd = [a-b for a, b in zip(e12, e26)]
    signal = ema(macd, 9)
    histogram = [(a-b)/p*100 for a, b, p in zip(macd, signal, values)]
    last = recent[-1][2]
    m5 = number(last.get('change_5m_pct'))
    h1 = number(last.get('change_1h_pct'))
    volume_hour = number(last.get('volume_1h_usd'))
    volume_day = number(last.get('volume_24h_usd'))
    buys = number(last.get('buys_1h'))
    sells = number(last.get('sells_1h'))
    age = number(last.get('age_hours'))
    liquid = number(last.get('liquidity_usd'))
    pace = volume_hour/(volume_day/24) if volume_day and volume_hour is not None else None
    buyer_share = buys/(buys+sells) if buys is not None and sells is not None and buys+sells > 0 else None
    if any(x is None for x in (m5, h1, pace, buyer_share, liquid, age)):
        return None
    return dict(rsi14=rsi, ema12=e12[-1], ema26=e26[-1],
                previous_ema12=e12[-2], previous_close=values[-2],
                macd_hist_pct=histogram[-1],
                macd_hist_delta_pct=histogram[-1]-histogram[-2],
                prior_12_bar_high=max(values[-13:-1]), close=values[-1],
                change_5m_pct=m5, change_1h_pct=h1, volume_pace=pace,
                buyer_share=buyer_share, liquidity_usd=liquid, age_hours=age)


def passes(arm, f):
    m5, h1 = f['change_5m_pct'], f['change_1h_pct']
    pace, buy = f['volume_pace'], f['buyer_share']
    basic = (0 < m5 <= 12 and 0 < h1 <= 40 and pace >= .5 and buy >= .5)
    # The baseline is technical-only, not a claim that wallet/history/news
    # and Rugcheck admissions would have happened in the original account.
    if arm == 'existing_technical_gate':
        return basic
    liquid = f['liquidity_usd'] >= 250000 and f['age_hours'] >= 24
    if arm == 'ema_rsi_macd_trend':
        return (basic and liquid and f['close'] > f['ema12'] > f['ema26']
                and 48 <= f['rsi14'] <= 70 and f['macd_hist_pct'] > 0
                and f['macd_hist_delta_pct'] > 0 and h1 >= 2 and pace >= .7)
    if arm == 'macd_confirmed_breakout':
        return (basic and liquid and f['close'] > 1.003*f['prior_12_bar_high']
                and 55 <= f['rsi14'] <= 75 and f['macd_hist_pct'] > 0
                and f['macd_hist_delta_pct'] > 0 and h1 >= 3 and pace >= 1.2
                and buy >= .55)
    if arm == 'ema_pullback_reclaim':
        return (basic and liquid and 42 <= f['rsi14'] <= 62
                and f['previous_close'] <= f['previous_ema12']
                and f['close'] > f['ema12'] and f['macd_hist_pct'] > 0
                and pace >= .7)
    if arm == 'avoid_overheated_momentum':
        return (basic and not (f['rsi14'] > 75 or
                (m5 > 4 and f['macd_hist_delta_pct'] < 0)))
    raise ValueError('Unregistered TA arm')


def score(arm, rows):
    selected = [r for r in rows if arm in r['arms']]
    result = {'signals': len(selected), 'distinct_entry_days': len({
        x['at'][:10] for x in selected}), 'paper_entry_enabled': False}
    for minutes in HORIZONS:
        key = str(minutes)+'m'
        completed = [x for x in selected if key in x['outcomes']]
        priced = [x['outcomes'][key]['net_quote_roi_pct'] for x in completed
                  if 'net_quote_roi_pct' in x['outcomes'][key]]
        gains = sum(v > 0 for v in priced)
        result[key] = dict(priced=len(priced), missing=len(completed)-len(priced),
                           pending=len(selected)-len(completed), wins=gains,
                           losses=sum(v < 0 for v in priced),
                           net_mean_pct=round(statistics.mean(priced), 4) if priced else None,
                           stressed_net_mean_pct=round(statistics.mean(priced)-2, 4) if priced else None,
                           win_rate_pct=round(100*gains/len(priced),2) if priced else None,
                           distinct_priced_days=len({x['at'][:10] for x in completed
                              if 'net_quote_roi_pct' in x['outcomes'][key]}),
                           sufficient_for_live_or_GBP_review=False)
    return result


def advance(state, now):
    """Prospective quote study only: state.research only; no external providers."""
    research = state.setdefault('research', {})
    book = research.setdefault(KEY, dict(version=VERSION, registered_at=now.isoformat(),
                        fingerprint=FINGERPRINT, cycles=0,
                        status='COLLECTING_UNPROVEN', pending=[], completed=[],
                        automatic_promotion=False, requests_added=0))
    if book.get('fingerprint') != FINGERPRINT or book.get('version') != VERSION:
        book['status'] = 'FROZEN_CONFIGURATION_MISMATCH'
        return book
    if book.get('last_run') and timestamp(book['last_run']) >= now:
        return book
    rows = price_marks(research.get('pool_observations') or [], now)
    # Outcomes at explicitly fixed 5/30/60m horizons; never use older mark.
    for trial in list(book['pending']):
        opened = timestamp(trial['at'])
        marks = rows.get(trial['pool'], [])
        for minutes in HORIZONS:
            key = str(minutes)+'m'
            if key in trial['outcomes']:
                continue
            target = opened + dt.timedelta(minutes=minutes)
            if now < target:
                continue
            eligible = [(t,p) for t,p,_ in marks if
                        target <= t <= target+dt.timedelta(minutes=10)]
            if eligible:
                observed = eligible[0][1]
                trial['outcomes'][key] = {
                    'net_quote_roi_pct': round(100*(observed/trial['price']*.99/1.01-1), 4)}
            elif now > target+dt.timedelta(minutes=10):
                trial['outcomes'][key] = {'status': 'MISSING_TIMELY_FRESH_MARK'}
        if len(trial['outcomes']) == len(HORIZONS):
            book['pending'].remove(trial)
            book['completed'].append(trial)
    # Preserve counts of dropped observations; do not fabricate sample size.
    if len(book['completed']) > 800:
        count = len(book['completed'])-800
        book['pruned_completed'] = book.get('pruned_completed',0)+count
        book['completed'] = book['completed'][count:]
    passed = {str(s.get('mint')) for s in state.get('screening', [])
              if isinstance(s,dict) and s.get('status') == 'PASS' and s.get('mint')}
    sampled = 0
    earlier = book['pending'] + book['completed']
    for pool, marks in rows.items():
        if len(book['pending']) >= 160 or sampled >= 8:
            break
        if not marks or str(marks[-1][2].get('mint')) not in passed:
            continue
        features = indicators(marks, now)
        if features is None:
            continue
        if any(x['pool']==pool and 0 <= (now-timestamp(x['at'])).total_seconds()<3600
               for x in earlier):
            continue
        chosen = [arm for arm in ARMS if passes(arm,features)]
        if not chosen:
            continue
        candidate = dict(pool=pool, at=now.isoformat(), price=features['close'],
                         arms=chosen, outcomes={})
        book['pending'].append(candidate)
        earlier.append(candidate)
        sampled += 1
    observations = book['completed']+book['pending']
    book.update(last_run=now.isoformat(),cycles=book['cycles']+1,
                status='COLLECTING_UNPROVEN',registered_config=FINGERPRINT,
                pending_count=len(book['pending']),
                completed_count=len(book['completed']),
                eligible_mark_series=sum(indicators(m,now) is not None for m in rows.values()),
                screened_pass_mints=len(passed),new_shadow_signals=sampled,
                reports={arm:score(arm,observations) for arm in ARMS},
                note='Read-only comparison on screen-PASS pools using observed five-minute DEX marks. '
                     'RSI14/EMA12/26/MACD9 computed solely from prior marks. 1% each-side modeled '
                     'cost; extra 2 percentage points stress. No fills, no futures, no allocation, '
                     'no promotion. Historical 81-close selection is NOT forward proof.')
    return book


def safe_advance(state, now):
    try:
        return advance(state, now)
    except Exception as exc:
        state.setdefault('research',{}).setdefault(KEY,{}).update(
            status='RESEARCH_ERROR',error_type=type(exc).__name__,
            automatic_promotion=False)
        return None
