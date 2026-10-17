"""Evidence-gated adaptive research for a persistent, PAPER-ONLY wallet agent.

No brokerage integrations, no AI credit, no external dependencies, no live orders.
All shadow results are labelled simulated and are NEVER included in account equity.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from .shadow_retirement import update_retirements

VERSION = 2
COST_SIDE = 0.01
MAX_SHADOW_PER_STRATEGY = 2
MAX_SHADOW_POOL_FETCH = 4
MAX_STORED_SIGNALS = 2000
MAX_STORED_OBSERVATIONS = 2500
MAX_STORED_SHADOW_CLOSES = 2000
UTC = dt.timezone.utc

# Deterministic pre-registered candidates. These are experiments, not known edges.
STRATEGIES = {
    "quality": {"min_liq": 250_000, "min_volume": 350_000, "min_age_hours": 72,
                "min_change": -15, "max_change": 35, "max_lag": 120},
    "momentum": {"min_liq": 150_000, "min_volume": 300_000, "min_age_hours": 48,
                 "min_change": 5, "max_change": 45, "max_lag": 180},
}


def stamp(value):
    if isinstance(value, dt.datetime):
        value = value if value.tzinfo else value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def numeric(value, default=None):
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (ValueError, OverflowError, TypeError):
        return default


def wilson_lower(wins, n, z=1.96):
    if n <= 0:
        return 0.0
    p = wins / n
    z2 = z * z
    return max(0.0, (p + z2 / (2 * n) - z * math.sqrt(p * (1-p) / n + z2 / (4*n*n))) / (1 + z2/n))


def pnl_report(trades):
    """Report net P&L / drawdown and sample uncertainty, not theoretical certainty."""
    clean = [t for t in trades if numeric(t.get('net_pnl_gbp')) is not None]
    pnls = [float(t['net_pnl_gbp']) for t in clean]
    rois = [numeric(t.get('roi_pct')) for t in clean]
    reliable_rois = [r for r in rois if r is not None]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    n = len(pnls)
    gross_wins = sum(wins)
    gross_losses = abs(sum(losses))
    cumulative = 0.0
    high = 0.0
    max_dd = 0.0
    for amount in pnls:
        cumulative += amount
        high = max(high, cumulative)
        max_dd = max(max_dd, high - cumulative)
    avg = sum(pnls)/n if n else 0.0
    rn = len(reliable_rois)
    avg_roi = sum(reliable_rois)/rn if rn else None
    roi_se = (math.sqrt(sum((x-avg_roi)**2 for x in reliable_rois)/(rn-1))/math.sqrt(rn)
              if rn > 1 else None)
    se = (math.sqrt(sum((x-avg)**2 for x in pnls)/(n-1))/math.sqrt(n)
          if n > 1 else None)
    dates = set()
    unique_wallets = {t.get('wallet') for t in clean if t.get('wallet')}
    unique_pools = {t.get('token') for t in clean if t.get('token')}
    unique_signals = {t.get('signal_id') for t in clean if t.get('signal_id')}
    for trade in clean:
        at = stamp(trade.get('exit_at'))
        if at:
            dates.add(at.date().isoformat())
    return dict(closed=n, wins=len(wins), losses=len(losses),
                win_rate_pct=round(100*len(wins)/n, 2) if n else None,
                win_rate_wilson_lower_pct=round(100*wilson_lower(len(wins), n), 2) if n else None,
                net_gbp=round(sum(pnls), 4), avg_pnl_gbp=round(avg, 4),
                mean_net_roi_pct=round(avg_roi, 3) if avg_roi is not None else None,
                conservative_mean_roi_95_pct=round(avg_roi-1.96*roi_se, 3) if roi_se is not None else None,
                gross_wins_gbp=round(gross_wins, 4), gross_losses_gbp=round(gross_losses, 4),
                profit_factor=round(gross_wins/gross_losses, 3) if gross_losses else None,
                max_drawdown_gbp=round(max_dd, 4), distinct_exit_days=len(dates),
                distinct_wallets=len(unique_wallets), distinct_pools=len(unique_pools),
                distinct_signals=len(unique_signals),
                conservative_mean_95_gbp=round(avg-1.96*se, 4) if se is not None else None)


def wallet_report(state, wallet, trades=None):
    if trades is None:
        trades = [x for x in state.get('closed', []) if x.get('wallet') == wallet]
    profile = pnl_report(trades)
    n = profile['closed']
    roi = [numeric(x.get('roi_pct'), 0.0) for x in trades]
    mean_roi = sum(roi)/n if n else 0.0
    shrunk = mean_roi*n/(n+10) if n else 0.0
    biggest = max((numeric(x.get('net_pnl_gbp'), 0.0) for x in trades), default=0.0)
    excluding_best = profile['net_gbp']-max(biggest, 0)
    observed = state.get('observed', {}).get(wallet) or {}
    profile.update(seen=observed.get('count', 0), shrunk_roi_pct=round(shrunk, 3),
                   win_rate=profile['win_rate_pct'], net_gbp=round(profile['net_gbp'], 2),
                   excluding_best_gbp=round(excluding_best, 4))
    fraction, tier, reason = reinforcement_decision(profile)
    from .evaluation import certified
    if tier.startswith('reinforced') and not certified(state,'wallet:'+wallet):
        fraction,tier,reason=0.005,'exploration','Positive legacy evidence lacks registered out-of-sample validation'
    profile.update(risk_fraction=fraction, reinforcement_tier=tier,
                   reinforcement_reason=reason, identity_verified=False)
    return profile


def reinforcement_decision(s):
    """Only actual independently closed PAPER trades qualify, never shadow trades.

    Exposure never exceeds the legacy 1.5% equity cap; no levered or live execution.
    """
    n = s.get('closed', 0)
    shrunk = numeric(s.get('shrunk_roi_pct'), 0)
    if n >= 3 and shrunk < -1:
        return (0.0, 'suspended', 'Loss evidence: trader allocation suspended')
    pf = numeric(s.get('profit_factor'))
    if pf is None:
        pf = 1e12 if s.get('gross_wins_gbp', 0) > 0 and s.get('gross_losses_gbp', 0) == 0 else 0.0
    lower = numeric(s.get('win_rate_wilson_lower_pct'), 0)
    day_count = s.get('distinct_exit_days', 0)
    robust = (s.get('net_gbp', 0) > 0 and s.get('excluding_best_gbp', 0) > 0
              and shrunk > 0 and pf >= 1.25 and lower >= 35
              and s.get('distinct_pools',0)>=2
              and s.get('distinct_signals',0)>=n)
    if robust and n >= 15 and day_count >= 4 and pf >= 1.5 and lower >= 42:
        return (0.015, 'reinforced_2', '15+ distinct closures across 4+ days; robust positive closed-trade evidence')
    if robust and n >= 8 and day_count >= 2:
        return (0.010, 'reinforced_1', '8+ closures across 2+ days; positive net after excluding best win')
    return (0.005, 'exploration', 'Insufficient independent profitable closed-trade evidence')


def wallet_risk_fraction(stats):
    if 'risk_fraction' in stats:
        return float(stats['risk_fraction'])
    return 0.005


def ensure(state):
    research = state.setdefault('research', {})
    research.setdefault('version', VERSION)
    research.setdefault('wallet_activity', {})
    research.setdefault('signals', [])
    research.setdefault('pool_observations', [])
    research.setdefault('shadow_positions', [])
    research.setdefault('shadow_closed', [])
    research.setdefault('events', [])
    research.setdefault('entry_features', {})
    research.setdefault('last_status', 'INITIALISING')
    research.setdefault('last_run', None)
    research.setdefault('reinforcement_events', [])
    research.setdefault('wallet_tiers', {})
    research.setdefault('cycle_errors', [])
    return research


def observe_event(state, event, current, pool):
    """Called only on a newly deduplicated chain event. Never invents wallet P&L."""
    r = ensure(state)
    wallet = event['wallet']
    profiles = r['wallet_activity']
    p = profiles.setdefault(wallet, dict(buys=0, sells=0, observed_usd=0.0,
                                         last_seen=None, recent_pools=[]))
    kind = event['kind']
    p['buys' if kind == 'buy' else 'sells'] += 1
    p['observed_usd'] = round(p['observed_usd'] + (numeric(event.get('usd'), 0) or 0), 2)
    p['last_seen'] = event['timestamp'].isoformat()
    pools = p['recent_pools']
    if event['token'] not in pools:
        pools.append(event['token'])
        p['recent_pools'] = pools[-12:]
    # Bound state growth: lowest-frequency / oldest wallets can be reacquired later.
    if len(profiles) > 3000:
        ordered = sorted(profiles, key=lambda k: profiles[k]['last_seen'] or '', reverse=True)
        r['wallet_activity'] = {k: profiles[k] for k in ordered[:3000]}


def enrich_meta(raw, meta):
    """Capture only externally supplied fields, preserving missing values as None."""
    attrs = raw.get('attributes') or {}
    changes = attrs.get('price_change_percentage') or {}
    volumes = attrs.get('volume_usd') or {}
    transactions = attrs.get('transactions') or {}
    t1 = transactions.get('h1') or {}
    extras = dict(meta)
    extras.update(change_5m_pct=numeric(changes.get('m5')),
                  change_1h_pct=numeric(changes.get('h1')),
                  volume_1h_usd=numeric(volumes.get('h1')),
                  fdv_usd=numeric(attrs.get('fdv_usd')),
                  market_cap_usd=numeric(attrs.get('market_cap_usd')),
                  buys_1h=numeric(t1.get('buys')),
                  sells_1h=numeric(t1.get('sells')))
    return extras


def feature_buckets(features):
    """Pre-registered, coarse classes; not a trained AI or wallet identity proof."""
    result=[]
    liq=numeric(features.get('liquidity_usd'))
    momentum=numeric(features.get('change_24h_pct'))
    latency=numeric(features.get('signal_age_seconds'))
    if liq is not None:
        result.append('liq:250k+' if liq>=250000 else 'liq:100-250k')
    if momentum is not None:
        result.append('trend:positive' if momentum>=5 else 'trend:flat_or_negative')
    if latency is not None:
        result.append('lag:fast' if latency<=90 else 'lag:slow')
    return result


def feature_risk_multiplier(state, event):
    """Only PREVIOUS completed cycles' reports can affect current paper sizing."""
    reports=(state.get('research') or {}).get('feature_reports', {})
    features=next((x for x in reversed((state.get('research') or {}).get('signals', []))
                   if x.get('signal_id')==event.get('id')), None)
    if not features:
        return (1.0, 'No recorded entry-feature evidence')
    statuses=[reports.get(k, {}).get('status') for k in feature_buckets(features)]
    # Negative evidence takes priority over positive; don't stack multiplicative bets.
    if 'NEGATIVE_EVIDENCE' in statuses:
        return (0.5, 'Forward evidence supports reducing this feature cohort')
    from .evaluation import certified
    if any(reports.get(k,{}).get('status')=='POSITIVE_EVIDENCE' and certified(state,'feature:'+k) for k in feature_buckets(features)):
        return (1.25, 'Forward actual closed-trade feature cohort supports modest reinforcement')
    return (1.0, 'Feature cohorts are still collecting outcome evidence')


def feature_reports(state):
    """Training data is only ACTUAL closed paper trades with captured entry context."""
    r=ensure(state)
    groups=defaultdict(list)
    features=r.get('entry_features', {})
    for trade in state.get('closed', []):
        signal=features.get(trade.get('signal_id'))
        if not signal: continue  # Historical uninstrumented wins are never backfilled.
        for key in feature_buckets(signal):
            groups[key].append(trade)
    output={}
    for key,trades in groups.items():
        report=pnl_report(trades)
        n=report['closed']
        lower=report.get('conservative_mean_roi_95_pct')
        mean=report.get('mean_net_roi_pct')
        upper=2*mean-lower if lower is not None and mean is not None else None
        biggest=max((numeric(t.get('net_pnl_gbp'),0) for t in trades),default=0)
        net_wo_best=report['net_gbp']-max(0,biggest)
        diverse = (report['distinct_wallets']>=8 and report['distinct_pools']>=5
                   and report['distinct_signals']>=n)
        if (n>=40 and report['distinct_exit_days']>=14 and diverse and lower is not None
            and lower>0 and net_wo_best>0):
            status='POSITIVE_EVIDENCE'
        elif (n>=40 and report['distinct_exit_days']>=14 and diverse and upper is not None and upper<0):
            status='NEGATIVE_EVIDENCE'
        else:
            status='COLLECTING_EVIDENCE'
        report.update(status=status, net_excluding_best_gbp=round(net_wo_best,4))
        output[key]=report
    return output


def fast_shadow_pool(token, timeout_seconds=6):
    """One-shot research quote: bounded latency, unlike primary feed's retries.

    Does not trade and has no wallet/broker credentials. Caller records errors
    only in research health: the underlying paper account still runs normally.
    """
    import json
    import urllib.parse
    import urllib.request
    from .core import BASE, HEADERS
    uri = BASE + '/networks/solana/pools/' + urllib.parse.quote(str(token), safe='')
    uri += '?include=base_token'
    request = urllib.request.Request(uri, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or 'errors' in payload or not isinstance(payload.get('data'), dict):
        raise ValueError('Shadow market price response malformed or unavailable')
    return payload


def shadow_tokens(state):
    r = (state.get('research') or {})
    tokens = []
    for p in r.get('shadow_positions', []):
        token = p.get('token')
        if token and token not in tokens:
            tokens.append(token)
    return tokens[:MAX_SHADOW_POOL_FETCH]


def conflicting_keys(events):
    return {(ev['wallet'], ev['token']) for ev in events if ev.get('kind') == 'sell'}


def passes(strategy, meta, lag):
    p = STRATEGIES[strategy]
    change = numeric(meta.get('change_24h_pct'))
    age = numeric(meta.get('age_hours'))
    return (lag is not None and 0 <= lag <= p['max_lag']
            and numeric(meta.get('liquidity_usd'), 0) >= p['min_liq']
            and numeric(meta.get('volume_24h_usd'), 0) >= p['min_volume']
            and age is not None and age >= p['min_age_hours']
            and change is not None and p['min_change'] <= change <= p['max_change'])


def _event(r, current, action, **kw):
    r['events'].append(dict(at=current.isoformat(timespec='seconds'), action=action, **kw))
    r['events'] = r['events'][-300:]


def _close_shadow(r, pos, price, current, reason):
    proceeds = pos['notional_gbp'] * price / pos['entry_price_usd'] * (1-COST_SIDE)
    pnl = proceeds - pos['cost_gbp']
    roi = 100*pnl/pos['cost_gbp']
    closed = {**pos, 'exit_at':current.isoformat(timespec='seconds'),
              'exit_price_usd':price, 'exit_reason':reason,
              'net_pnl_gbp':round(pnl, 4), 'roi_pct':round(roi, 3)}
    r['shadow_closed'].append(closed)
    r['shadow_closed'] = r['shadow_closed'][-MAX_STORED_SHADOW_CLOSES:]
    r['shadow_positions'].remove(pos)
    _event(r, current, 'SHADOW_CLOSE', strategy=pos['strategy'],
           token=pos['token'], net_pnl_gbp=closed['net_pnl_gbp'], reason=reason)


def research_cycle(state, candidate_pools, prices, new_events, current):
    """Called after screening/events, before paper trades; never alters live account.

    Shadow candidates use ONLY features available at signal time. No lookahead.
    Missing prices preserve open shadow positions without fictional valuations.
    """
    r = ensure(state)
    metadatas = {p['pool']: p for p in candidate_pools}
    allowed = {x.get('mint') for x in state.get('screening', []) if x.get('status') == 'PASS'}
    selling = conflicting_keys(new_events)
    for pos in list(r['shadow_positions']):
        price = numeric(prices.get(pos['token']))
        if price is None or price <= 0:
            continue
        roi = 100*((price/pos['entry_price_usd'])*(1-COST_SIDE)/(1+COST_SIDE)-1)
        age = (current-stamp(pos['opened_at'])).total_seconds()/3600
        exit_reason = ('observed wallet sell' if (pos['wallet'],pos['token']) in selling else
                       '12% stop' if roi <= -12 else '20% target' if roi >= 20 else
                       '6h maximum' if age >= 6 else None)
        if exit_reason:
            _close_shadow(r, pos, price, current, exit_reason)
    r['pool_observations'].extend([dict(at=current.isoformat(timespec='seconds'),
                                        pool=meta['pool'], name=meta['name'],
                                        mint=meta['mint'], price_usd=meta['price_usd'],
                                        liquidity_usd=meta['liquidity_usd'],
                                        volume_24h_usd=meta['volume_24h_usd'],
                                        change_24h_pct=meta.get('change_24h_pct'),
                                        token_safety=('PASS' if meta['mint'] in allowed else 'NOT_PASS'),
                                        change_1h_pct=meta.get('change_1h_pct'),
                                        change_5m_pct=meta.get('change_5m_pct'),
                                        volume_1h_usd=meta.get('volume_1h_usd'),
                                        fdv_usd=meta.get('fdv_usd'),
                                        market_cap_usd=meta.get('market_cap_usd'),
                                        buys_1h=meta.get('buys_1h'),
                                        sells_1h=meta.get('sells_1h'))
                                   for meta in candidate_pools])
    r['pool_observations'] = r['pool_observations'][-MAX_STORED_OBSERVATIONS:]
    # Freeze losing experiments only when multiple days, wallets and pools
    # provide strong negative PAPER evidence. Open shadows still close normally.
    retirement_reports = {
        name:pnl_report([t for t in r['shadow_closed'] if t.get('strategy')==name])
        for name in STRATEGIES
    }
    update_retirements(r,retirement_reports,current)
    original_last_run = stamp(state.get('last_run'))
    for ev in sorted(new_events, key=lambda e:e['timestamp']):
        meta = metadatas.get(ev['token'])
        if not meta:
            continue
        lag = (current - ev['timestamp']).total_seconds()
        sample = dict(at=current.isoformat(timespec='seconds'),
                      signal_id=ev['id'], signal_at=ev['timestamp'].isoformat(timespec='seconds'),
                      signal_age_seconds=round(lag, 1), kind=ev['kind'],
                      wallet=ev['wallet'], token=ev['token'],
                      pool_name=meta['name'], observed_usd=ev.get('usd'),
                      liquidity_usd=meta['liquidity_usd'],
                      volume_24h_usd=meta['volume_24h_usd'],
                      change_24h_pct=meta.get('change_24h_pct'),
                      age_hours=meta.get('age_hours'),
                      wallet_seen=(state.get('observed', {}).get(ev['wallet']) or {}).get('count', 0),
                      token_safety=('PASS' if meta['mint'] in allowed else 'NOT_PASS'),
                      wallet_identity_verified=False,
                      change_1h_pct=meta.get('change_1h_pct'),
                      change_5m_pct=meta.get('change_5m_pct'),
                      volume_1h_usd=meta.get('volume_1h_usd'),
                      fdv_usd=meta.get('fdv_usd'),
                      market_cap_usd=meta.get('market_cap_usd'),
                      buys_1h=meta.get('buys_1h'),
                      sells_1h=meta.get('sells_1h'))
        r['signals'].append(sample)
        if ev['kind'] != 'buy':
            continue
        if original_last_run is None or ev['timestamp'] <= original_last_run:
            continue  # Never backfill shadow wins into live-forward evidence.
        if (ev['wallet'],ev['token']) in selling:
            _event(r, current, 'CONFLICT_SIGNAL', wallet=ev['wallet'], token=ev['token'])
            continue
        if sample['token_safety'] != 'PASS' or sample['wallet_seen'] < 3:
            continue
        price = numeric(prices.get(ev['token']))
        if price is None or price <= 0:
            continue
        for strategy in STRATEGIES:
            if strategy in r.get('retired_shadow_strategies',{}):
                continue
            if not passes(strategy, meta, lag):
                continue
            active = [p for p in r['shadow_positions'] if p['strategy'] == strategy]
            if len(active) >= MAX_SHADOW_PER_STRATEGY:
                continue
            if any(p['token'] == ev['token'] or p['wallet'] == ev['wallet'] for p in active):
                continue
            if any(p['strategy'] == strategy and p['wallet'] == ev['wallet']
                   and p['token'] == ev['token'] and
                   0 <= (current-stamp(p['exit_at'])).total_seconds() < 1800
                   for p in r['shadow_closed'][-50:]):
                continue
            pos = dict(strategy=strategy, wallet=ev['wallet'], token=ev['token'],
                       pool_name=meta['name'], opened_at=current.isoformat(timespec='seconds'),
                       signal_at=ev['timestamp'].isoformat(timespec='seconds'),
                       signal_id=ev['id'], entry_price_usd=price,
                       notional_gbp=10.0, cost_gbp=10.1,
                       entry_features=sample)
            r['shadow_positions'].append(pos)
            _event(r, current, 'SHADOW_OPEN', strategy=strategy,
                   token=ev['token'], signal_lag_seconds=round(lag,1))
    r['signals'] = r['signals'][-MAX_STORED_SIGNALS:]
    return r


def finalize(state, current):
    """Associate true, post-execution paper positions/closures with recorded features."""
    r = ensure(state)
    from .evaluation import safe_update
    safe_update(state,current)
    features = r['entry_features']
    lookup = {s['signal_id']:s for s in r['signals']}
    for trade in [*state.get('positions', []), *state.get('closed', [])[-100:]]:
        signal_id = trade.get('signal_id')
        if signal_id and signal_id in lookup and signal_id not in features:
            features[signal_id] = lookup[signal_id]
    valid_ids = {p.get('signal_id') for p in state.get('positions', [])}
    valid_ids.update(p.get('signal_id') for p in state.get('closed', [])[-2000:])
    r['entry_features'] = {k:v for k,v in features.items() if k in valid_ids}
    grouped = defaultdict(list)
    for paper_close in state.get('closed', []):
        grouped[paper_close['wallet']].append(paper_close)
    rankings = []
    previous_tiers = r['wallet_tiers']
    for wallet, wallet_trades in grouped.items():
        stats = wallet_report(state, wallet, wallet_trades)
        rankings.append(dict(wallet=wallet, **stats))
        previous = previous_tiers.get(wallet, 'exploration')
        if stats['reinforcement_tier'] != previous:
            r['reinforcement_events'].append(dict(at=current.isoformat(timespec='seconds'),
                    wallet=wallet, from_tier=previous,
                    to_tier=stats['reinforcement_tier'],
                    closed_trades=stats['closed'], net_gbp=stats['net_gbp'],
                    evidence=stats['reinforcement_reason']))
        previous_tiers[wallet] = stats['reinforcement_tier']
    rankings.sort(key=lambda x:(x['net_gbp'],x['closed']), reverse=True)
    r['wallet_rankings'] = rankings[:200]
    r['reinforcement_events'] = r['reinforcement_events'][-100:]
    shadow_reports = {}
    for strategy in STRATEGIES:
        report = pnl_report([x for x in r['shadow_closed'] if x['strategy']==strategy])
        report['open_positions'] = sum(x['strategy']==strategy for x in r['shadow_positions'])
        # Statistical strength and sample diversity before even considering an experiment candidate.
        lower = report['conservative_mean_roi_95_pct']
        pf = numeric(report.get('profit_factor'))
        if pf is None:
            pf = 1e12 if report['gross_wins_gbp'] > 0 and report['gross_losses_gbp'] == 0 else 0.0
        eligible = (report['closed']>=40 and report['distinct_exit_days']>=14
                    and lower is not None and lower>0 and pf>=1.3
                    and report['distinct_wallets']>=8 and report['distinct_pools']>=5)
        report['status'] = 'CANDIDATE_FOR_REVIEW' if eligible else 'COLLECTING_EVIDENCE'
        report['live_promoted'] = False
        shadow_reports[strategy] = report
    update_retirements(r,shadow_reports,current)
    r['shadow_reports'] = shadow_reports
    r['feature_reports'] = feature_reports(state)
    r['actual_report'] = pnl_report(state.get('closed', []))
    r['actual_report']['open_positions'] = len(state.get('positions', []))
    r['last_run'] = current.isoformat(timespec='seconds')
    r['last_status'] = 'SHADOW_DATA_DEGRADED' if r.get('cycle_errors') else 'OK'
    r['methodology'] = ('Paper-only, net of 1% modeled adverse costs each side; shadow returns '
                        'are counterfactual and not added to account balance. '
                        'Wallet identity is unverified; no claim of AI learning or real fills.')
    return r
