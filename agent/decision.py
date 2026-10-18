"""Versioned, explainable entry policy. Closed outcomes only; no fitted hindsight.

Defensive controls are active immediately. Positive selection uses shrunk net ROI;
positive exposure still requires the existing registered OOS certification.
"""
import datetime as dt
from .adaptive import numeric, stamp, pnl_report

VERSION = 1


def initialize(state, current):
    r = state.setdefault('research', {})
    return r.setdefault('decision_v1', dict(version=VERSION, registered_at=current.isoformat(),
        pool_mints={}, assessments={}, counters={}, status='UNPROVEN',
        policy={'base_cooldown_minutes':30, 'loss_cooldown_minutes':120,
                'repeated_loss_cooldown_hours':24, 'lookback_hours':24,
                'positive_exposure_requires_oos':True, 'automatic_shadow_promotion':False}))


def remember(state, pools, current):
    d = initialize(state, current)
    for p in (state.get('research') or {}).get('pool_observations', []) + list(pools):
        if p.get('mint') and p.get('pool'):
            d['pool_mints'][p['pool']] = p['mint']
    # Retain aliases referenced by actual history, plus recent discovered pools.
    keep = {t['token'] for t in state.get('closed', []) + state.get('positions', [])}
    keep.update(p['pool'] for p in pools)
    d['pool_mints'] = {k:v for k,v in d['pool_mints'].items() if k in keep}


def history(state, pool, current):
    d = initialize(state, current)
    aliases = d['pool_mints']; mint = aliases.get(pool)
    rows = []
    seen = set()
    for t in state.get('closed', []):
        at = stamp(t.get('exit_at'))
        same = t.get('token') == pool or (mint and (t.get('mint') or aliases.get(t.get('token'))) == mint)
        sid = t.get('signal_id')
        if same and at and 0 <= (current-at).total_seconds() <= 86400 and sid and sid not in seen:
            seen.add(sid); rows.append(t)
    rows.sort(key=lambda x:x['exit_at'])
    report = pnl_report(rows)
    streak = 0
    for t in reversed(rows):
        if numeric(t.get('net_pnl_gbp'),0) >= 0: break
        streak += 1
    losses = [t for t in rows if numeric(t.get('net_pnl_gbp'),0) < 0]
    until = None
    if rows:
        until = stamp(rows[-1]['exit_at']) + dt.timedelta(minutes=30)
    if losses:
        last = stamp(losses[-1]['exit_at'])
        until = max(until, last + dt.timedelta(minutes=120))
        if streak >= 3 or (len(losses) >= 3 and report['net_gbp'] < 0):
            until = max(until, last + dt.timedelta(hours=24))
    rois = [numeric(t.get('roi_pct'),0) for t in rows]
    # Selection only, no automatic risk increase. Shrink sparse observations.
    score = sum(rois)/(len(rows)+10)
    report.update(loss_streak=streak, shrunk_roi_pct=round(score,4),
                  cooldown_until=until.isoformat() if until else None)
    return report


def assess(state, meta, current):
    report = history(state, meta['pool'], current)
    reasons = []
    until = stamp(report['cooldown_until'])
    if until and current < until: reasons.append('token-wide history cooldown')
    m5, h1, v1, v24, buys, sells = [numeric(meta.get(k)) for k in
        ('change_5m_pct','change_1h_pct','volume_1h_usd','volume_24h_usd','buys_1h','sells_1h')]
    complete = all(x is not None for x in (m5,h1,v1,v24,buys,sells))
    ratio = v1/(v24/24) if v24 and v1 is not None else None
    pressure = buys/(buys+sells) if buys is not None and sells is not None and buys+sells > 0 else None
    if not complete or pressure is None: reasons.append('technical inputs incomplete')
    else:
        if min(v1,v24,buys,sells)<0: reasons.append('invalid negative volume or trade counts')
        if h1 <= 0 or m5 <= 0: reasons.append('positive 5m and 1h momentum required')
        if m5 > 12 or h1 > 40: reasons.append('overextended price move')
        if ratio is None or ratio < .5: reasons.append('hourly volume fading versus daily pace')
        if pressure < .5: reasons.append('sell-dominated transaction count')
    news = (state.get('research') or {}).get('news_v1') or {}
    fetched = stamp(news.get('checked_at'))
    fresh = fetched and 0 <= (current-fetched).total_seconds() <= 1800
    if not fresh or news.get('status') not in ('OK','PARTIAL'):
        reasons.append('news context unavailable or stale')
    elif news.get('risk_off'): reasons.append('recent Solana or broad-market adverse headline')
    return dict(version=VERSION, allowed=not reasons, reasons=reasons,
                history=report, selection_score=report['shrunk_roi_pct'],
                technical={'change_5m_pct':m5,'change_1h_pct':h1,
                           'volume_pace_ratio':ratio,'buy_count_share':pressure},
                news={'status':news.get('status','UNAVAILABLE'), 'checked_at':news.get('checked_at'),
                      'risk_off':news.get('risk_off'), 'evidence':news.get('risk_evidence',[])})


def prepare(state, pools, current):
    remember(state, pools, current)
    d = initialize(state, current)
    d['assessments'] = {p['pool']:assess(state,p,current) for p in pools}
    d['last_run'] = current.isoformat()
    d['pool_reports'] = {p['pool']:history(state,p['pool'],current) for p in pools}
    # Frozen, separate GBP winner-trait shadow hypothesis; not allocation.
    from .winner_traits import VERSION as WIN_VERSION, classify, source_hash
    candidate_hash = source_hash()
    trial = d.setdefault('winner_traits_v1', dict(
        version=WIN_VERSION, registered_at=current.isoformat(),
        source_sha256=candidate_hash, status='COLLECTING', automatic_promotion=False))
    if trial['source_sha256'] != candidate_hash or trial.get('invalidated_at'):
        trial.setdefault('invalidated_at', current.isoformat())
        trial['status'] = 'INVALIDATED'
        d['winner_traits_candidates'] = {}
    else:
        d['winner_traits_candidates'] = {
            p['pool']: classify(p, d['assessments'][p['pool']]) for p in pools}
    return d


def entry_assessment(state, event, current):
    d = (state.get('research') or {}).get('decision_v1')
    if not d: return None  # Backwards compatible standalone simulator helper.
    a = d.get('assessments', {}).get(event['token'])
    if not a: return dict(allowed=False,reasons=['no current technical assessment'])
    # Refresh history after closures during this very cycle; another wallet cannot bypass it.
    a = {**a, 'history':history(state,event['token'],current), 'reasons':list(a['reasons'])}
    until = stamp(a['history']['cooldown_until'])
    if until and current < until and 'token-wide history cooldown' not in a['reasons']:
        a['reasons'].insert(0,'token-wide history cooldown')
    a['allowed'] = not a['reasons']
    return a


def observe_forward(state, events, prices, current):
    """Predecision cohorts, one observation per token per hour, fixed future horizons.

    Sampled quote returns net of 1% each side, NOT portfolio returns. No extra
    provider calls. Missing/late future quotes stay missing; never backfilled.
    """
    d=initialize(state,current)
    pending=d.setdefault('forward_pending',[]);done=d.setdefault('forward_outcomes',[])
    for x in list(pending):
        age=(current-stamp(x['at'])).total_seconds()
        price=numeric(prices.get(x['token']))
        for minute in (5,30,60):
            key=str(minute)+'m'
            if age>=minute*60 and key not in x['outcomes']:
                if age<=minute*60+600 and price is not None and price>0:
                    x['outcomes'][key]={'at':current.isoformat(),
                        'net_quote_roi_pct':round(100*(price/x['price']*.99/1.01-1),4)}
                elif age>minute*60+600:
                    x['outcomes'][key]={'status':'MISSING_FRESH_QUOTE'}
        if len(x['outcomes'])==3:
            done.append(x);pending.remove(x)
    conflicting={(e['wallet'],e['token']) for e in events if e['kind']=='sell'}
    for ev in events:
        if (ev['wallet'],ev['token']) in conflicting:continue
        if ev['kind']!='buy' or (state.get('observed',{}).get(ev['wallet']) or {}).get('count',0)<3: continue
        if not 0 <= (current-ev['timestamp']).total_seconds()<=240: continue
        if any(y['token']==ev['token'] and (current-stamp(y['at'])).total_seconds()<3600 for y in pending+done):continue
        price=numeric(prices.get(ev['token']));a=entry_assessment(state,ev,current)
        if price is None or price<=0 or a is None:continue
        if len(pending)>=64:break
        record=dict(signal_id=ev['id'],token=ev['token'],at=current.isoformat(),price=price,
                    accepted_by_policy=a['allowed'],reasons=a['reasons'],outcomes={})
        trial = d.get('winner_traits_v1') or {}
        if trial.get('status') == 'COLLECTING':
            from .winner_traits import VERSION as WIN_VERSION
            record['winner_traits_version'] = WIN_VERSION
            record['winner_traits_v1'] = bool(
                d.get('winner_traits_candidates', {}).get(ev['token'], False))
        pending.append(record)
    d['forward_outcomes']=done[-500:]
    summary={}
    for accepted in (True,False):
        cohort=[x for x in done+pending if x['accepted_by_policy']==accepted]
        result={}
        for minute in (5,30,60):
            key=str(minute)+'m'
            mature=[x for x in cohort if key in x['outcomes']]
            values=[x['outcomes'][key]['net_quote_roi_pct'] for x in mature if 'net_quote_roi_pct' in x['outcomes'][key]]
            result[key]={'priced':len(values),'missing':len(mature)-len(values),'pending':len(cohort)-len(mature),
                         'mean_net_quote_roi_pct':round(sum(values)/len(values),4) if values else None}
        summary['accepted' if accepted else 'blocked']=result
    d['forward_summary']=summary
    d['forward_description']='Forward sampled quote cohorts, one per pool/hour; costs 1% each side; not strategy P&L or causal proof; no automatic promotion.'
    trial=d.get('winner_traits_v1')
    if trial:
        from .winner_traits import forward_report
        trial['forward']=forward_report(done+pending,trial['registered_at'])
        trial['last_run']=current.isoformat()
