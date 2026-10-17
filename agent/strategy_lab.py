"""Forward-only learning and deterministic profit protection for PAPER futures.

No orders, credentials, state resets, look-ahead pricing or auto risk increases.
Sampling only observes executable bid/ask prices already obtained by the parent.
"""
import datetime as dt
import math

UTC = dt.timezone.utc
FEE = .0005
SLIP = .001
HORIZONS = (5, 30, 60)
COOLDOWN_SECONDS = 3600
MAX_SIGNALS = 2500


def _stamp(v):
    if isinstance(v, dt.datetime):
        return v if v.tzinfo else None
    try:
        t = dt.datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        return t if t.tzinfo else None
    except (TypeError, ValueError):
        return None


def market_regime(f):
    """Immutable, deliberately coarse regime labels using completed 5m candles."""
    if f['pump'] >= .03 and f['drawdown'] >= 1 and f['lower_closes']:
        return 'POST_PUMP_REVERSAL'
    if abs(f['r1h']) >= .006 and f['volume_ratio'] >= 1.2:
        return 'ACTIVE_TREND'
    return 'MIXED_OR_QUIET'


def has_cost_room(f, quote):
    """Only trade when a two-ATR price move exceeds a conservative cost hurdle.

    A volatility proxy is NOT a predicted return or a proof of positive edge.
    """
    try:
        spread = (quote['ask']-quote['bid'])/quote['mid']
        room = 2*f['atr']/f['close']
        cost = 2*(FEE+SLIP)+spread
        return all(math.isfinite(x) for x in (spread,room,cost)) and spread >= 0 and room >= 1.5*cost
    except (TypeError, KeyError, ZeroDivisionError):
        return False


def observed_net_roi(direction, entry, quote):
    """Return on entry notional net of bid/ask, 0.1% slippage and both fees."""
    if direction not in (-1, 1) or entry <= 0 or not isinstance(quote, dict):
        return None
    bid, ask = quote.get('bid'), quote.get('ask')
    if not isinstance(bid, (int, float)) or not isinstance(ask, (int, float)):
        return None
    if not (math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask):
        return None
    exit_px = bid*(1-SLIP) if direction == 1 else ask*(1+SLIP)
    return 100*(direction*(exit_px-entry)/entry - FEE*(1+exit_px/entry))


def observe_forward(book, now, quotes, candidates, entered_symbol=None):
    """Score previously sampled signals BEFORE registering fresh ones.

    No retrospective candles, fabricated intrabar highs, provider calls, or
    false zero return when a future quote is missing.
    """
    rows = book.setdefault('forward_signals', [])
    for r in rows:
        at = _stamp(r.get('at'))
        if at is None:
            continue
        seconds = (now-at).total_seconds()
        if seconds < 0:
            continue
        q = quotes.get(r['symbol'])
        for minute in HORIZONS:
            key = str(minute)+'m'
            if key in r['outcomes'] or seconds < minute*60:
                continue
            if seconds <= minute*60+600 and q:
                roi = observed_net_roi(r['direction'], r['entry'], q)
                if roi is not None:
                    r['outcomes'][key] = {'net_roi_pct':round(roi, 5), 'at':now.isoformat()}
            if key not in r['outcomes'] and seconds > minute*60+600:
                r['outcomes'][key] = {'status':'MISSING_QUOTE'}
    for c in candidates[:12]:
        q = quotes.get(c['symbol'])
        if not q:
            continue
        s, direction = c['setup'], c['direction']
        if any(r['symbol'] == c['symbol'] and r['setup'] == s and
               (at := _stamp(r['at'])) and 0 <= (now-at).total_seconds() < COOLDOWN_SECONDS
               for r in rows):
            continue
        entry = q['ask']*(1+SLIP) if direction == 1 else q['bid']*(1-SLIP)
        reason = 'ENTERED' if entered_symbol == c['symbol'] else (c.get('rejection_reason') or 'NOT_SELECTED')
        rows.append({'at':now.isoformat(), 'symbol':c['symbol'], 'setup':s,
                     'direction':direction, 'regime':c['regime'], 'entry':entry,
                     'decision':'ENTERED' if reason == 'ENTERED' else 'OBSERVED_NOT_ENTERED',
                     'rejection_reason':None if reason=='ENTERED' else reason,
                     'policy_revision':'v4.1', 'rule_version':book.get('version'), 'outcomes':{}})
    if len(rows) > MAX_SIGNALS:
        del rows[:len(rows)-MAX_SIGNALS]
    book['forward_summary'] = forward_summary(rows)
    book['missed_winners'] = missed_winners(rows)


def forward_summary(rows):
    summary = {}
    for horizon in ('5m', '30m', '60m'):
        priced = [r['outcomes'][horizon]['net_roi_pct'] for r in rows
                  if horizon in r['outcomes'] and 'net_roi_pct' in r['outcomes'][horizon]]
        missing = sum(r['outcomes'].get(horizon,{}).get('status') == 'MISSING_QUOTE' for r in rows)
        summary[horizon] = {'priced':len(priced), 'missing':missing,
                            'mean_net_roi_pct':round(sum(priced)/len(priced), 4) if priced else None}
    return summary


def missed_winners(rows, limit=12):
    """Real observations of rejected setups, NEVER realised paper trades.

    Samples with missing 60m prices are not treated as wins or losses. Report
    both successes and failures rather than cherry-picking success-only stats.
    """
    cohorts=[r for r in rows if r.get('decision')=='OBSERVED_NOT_ENTERED'
             and r.get('policy_revision')=='v4.1'
             and isinstance(r.get('outcomes',{}).get('60m',{}).get('net_roi_pct'),(int,float))]
    winners=sorted((r for r in cohorts if r['outcomes']['60m']['net_roi_pct']>0),
                   key=lambda r:r['outcomes']['60m']['net_roi_pct'],reverse=True)
    def digest(r):
        return {'at':r['at'], 'symbol':r['symbol'], 'setup':r['setup'],
                'reason':r.get('rejection_reason') or 'NOT_SELECTED',
                'net_quote_roi_pct':r['outcomes']['60m']['net_roi_pct'],
                'status':'HYPOTHETICAL_FORWARD_QUOTE_NOT_EXECUTED'}
    total=len(cohorts)
    return {'evaluated':total, 'winners':len(winners),
            'losers_or_flat':total-len(winners),
            'win_rate_pct':round(100*len(winners)/total,2) if total else None,
            'net_mean_pct':round(sum(r['outcomes']['60m']['net_roi_pct'] for r in cohorts)/total,4) if total else None,
            'top_missed':list(map(digest,winners[:limit])),
            'description':'Missed eligible/blocked setup quote outcomes at 60m, net of modelled spread, fees and slippage; no actual fills or causal comparison.'}


def priority_score(base, f, quote, learning, trade_edge=0.):
    """Comparable cost-aware relative rank, not a return prediction.

    Bounded components avoid a raw volatility-scaled momentum score burying
    prospective learning. Total risk fraction never changes here.
    """
    try:
        mid=quote['mid']
        spread=(quote['ask']-quote['bid'])/mid
        atr_pct=f['atr']/f['close']
        activity=max(0.,min(f['volume_ratio'],4.)-1.)
        base_score=math.log1p(min(max(float(base),0.),30.))
        spread_penalty=min(2., spread/max(atr_pct,.0001))
        a=float(learning.get('adjustment',0.))
        edge=min(.75,max(-.75,float(trade_edge)))
        score=base_score + .2*activity - spread_penalty + a + edge
        return round(score,6) if math.isfinite(score) else -999.
    except (KeyError,TypeError,ValueError,ZeroDivisionError):
        return -999.


def recovery_state(book, setup, now, rows):
    """Restart a loss-paused setup only after NEW forward shadow evidence.

    No automatic expiry of a losing setup. Four 60m quotes over two distinct
    days, >=3 profitable, and positive aggregate net quote ROI after a full
    24h wait are required. These are cautious operational gates, not validation.
    """
    records=book.setdefault('recovery_v1',{})
    record=records.get(setup)
    after=_stamp(record.get('recovered_at')) if record and record.get('status')=='RECOVERED' else None
    valid=[t for t in rows if (end:=_stamp(t.get('exit_at'))) and end<=now and
           (after is None or end>after)]
    last_day=[t for t in valid if 0 <= (now-_stamp(t['exit_at'])).total_seconds()<86400]
    last_three=last_day[-3:]
    trigger=(len(last_three)==3 and all(t['net_usd']<0 for t in last_three))
    if trigger and (not record or record['status']=='RECOVERED'):
        at=last_three[-1]['exit_at']
        record={'status':'PAUSED','since':at, 'trigger':'THREE_RECENT_LOSSES',
                'recovered_at':None, 'recovery_count':0, 'evaluated':0}
        records[setup]=record
    if not record or record.get('status')=='RECOVERED':
        return {'allowed':True,'status':record['status'] if record else 'ACTIVE',
                'evaluated':record.get('evaluated',0) if record else 0}
    started=_stamp(record.get('since'))
    if started is None or now-started < dt.timedelta(hours=24):
        record['status']='PAUSED'
        return {'allowed':False,'status':'PAUSED','evaluated':0}
    # Only future samples that were NOT actually entered after suspension.
    tests=[r for r in book.get('forward_signals',[]) if
           r.get('setup')==setup and r.get('rule_version')==book.get('version') and
           r.get('decision')=='OBSERVED_NOT_ENTERED' and
           (t:=_stamp(r.get('at'))) and t>started and t<=now and
           isinstance(r.get('outcomes',{}).get('60m',{}).get('net_roi_pct'),(int,float))]
    # Suppress multiple time-coincident signals from several correlated coins.
    distinct={}
    for r in tests:
        key=r['at'][:13]
        distinct.setdefault(key,r)
    tests=list(distinct.values())
    value=[r['outcomes']['60m']['net_roi_pct'] for r in tests]
    record['evaluated']=len(value)
    record['recovery_count']=sum(x>0 for x in value)
    day_count=len({r['at'][:10] for r in tests})
    if len(value)>=4 and day_count>=2 and sum(x>0 for x in value)>=3 and sum(value)>0:
        record.update(status='RECOVERED',recovered_at=now.isoformat())
        return {'allowed':True,'status':'RECOVERED','evaluated':len(value)}
    record['status']='RETESTING'
    return {'allowed':False,'status':'RETESTING','evaluated':len(value)}


def context_adjustment(book, setup, regime):
    """Selection-only forward evidence; no reward based on shadow P&L alone.

    Independent days and >=20 hourly-deduplicated forward observations required;
    a standard-error interval is a provisional gate, not statistical proof.
    """
    version = book.get('version')
    rows = [(r['at'], r['outcomes']['60m']['net_roi_pct'])
            for r in book.get('forward_signals', [])
            if r.get('setup') == setup and r.get('regime') == regime and
               r.get('rule_version') == version and
               'net_roi_pct' in r.get('outcomes',{}).get('60m',{})]
    days = len({t[:10] for t,_ in rows})
    if len(rows) < 20 or days < 7:
        return {'status':'COLLECTING', 'adjustment':0., 'observations':len(rows), 'days':days}
    values = [v for _,v in rows]
    n = len(values)
    mean = sum(values)/n
    std = math.sqrt(sum((v-mean)**2 for v in values)/(n-1))
    uncertainty = 1.96*std/math.sqrt(n)
    if mean + uncertainty < 0:
        status, adjustment = 'NEGATIVE_FORWARD', -1.
    elif mean - uncertainty > 0:
        status, adjustment = 'POSITIVE_FORWARD', .5
    else:
        status, adjustment = 'INCONCLUSIVE', 0.
    return {'status':status, 'adjustment':adjustment, 'observations':n,
            'days':days, 'mean_net_roi_pct':round(mean,4),
            'uncertainty_95_pct':round(uncertainty,4)}


def _stop_mid_for_target_net(p, target_net, quote):
    """Model stop against CURRENT bid/ask spread, slippage and both fees."""
    units = p['units']
    mid = quote['mid']
    if units <= 0 or mid <= 0:
        return None
    expenses = p['entry_fees']+p['carry_usd']
    if p['direction'] == 1:
        factor = (quote['bid']/mid)*(1-SLIP)*(1-FEE)
        return (p['entry']*units+expenses+target_net)/(units*factor)
    if p['direction'] == -1:
        factor = (quote['ask']/mid)*(1+SLIP)*(1+FEE)
        return (p['entry']*units-expenses-target_net)/(units*factor)
    return None


def improved_stop(p, quote, net, atr):
    """After +0.5R, ratchet breakeven; after +1R, retain part of paper net.

    Trigger evaluated only on the NEXT scheduled observation; stop execution is
    at the NEXT observed bid/ask, never a guaranteed price. No intrabar claims.
    """
    if not isinstance(quote, dict):
        return None
    try:
        market_mid, bid, ask = (quote[k] for k in ('mid','bid','ask'))
    except KeyError:
        return None
    if not all(isinstance(x, (int,float)) and math.isfinite(x) for x in (market_mid,bid,ask,net)):
        return None
    if not (0 < bid <= market_mid <= ask):
        return None
    risk = p.get('risk_usd',0)
    if not isinstance(risk,(int,float)) or risk<=0 or net < .5*risk:
        return None
    target = 0 if net < risk else max(.15*risk, .35*net)
    candidate = _stop_mid_for_target_net(p,target,quote)
    if candidate is None:
        return None
    direction = p['direction']
    if net >= risk and isinstance(atr,(int,float)) and math.isfinite(atr) and atr>0:
        trail = p['best'] - direction*2*atr
        candidate = max(candidate,trail) if direction==1 else min(candidate,trail)
    # Only set a stop behind the current mark. Never loosen an existing stop.
    if direction*(market_mid-candidate)<=0 or direction*(candidate-p['stop'])<=0:
        return None
    return candidate
