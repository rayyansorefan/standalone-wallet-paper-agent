"""Pre-registered forward evaluation, never account P&L or an optimiser.

Fixed chronological training/validation, purged overlapping entries, daily
cluster uncertainty and family-wise margin. Approximate statistical evidence
is a review gate, not proof of causality, owner identity or future profits.
"""
import datetime as dt
import math
import hashlib
import json
from collections import defaultdict

VERSION = 1
TRAIN_MIN = 40
TEST_MIN = 20
TRAIN_DAYS = 14
TEST_DAYS = 7
Z_FAMILY = 4.2  # conservative normal approximation, <=256 predeclared reports
MAX_REPORTS = 256
UTC = dt.timezone.utc


def stamp(v):
    try:
        t=dt.datetime.fromisoformat(str(v).replace('Z','+00:00'))
        return t.astimezone(UTC) if t.tzinfo else None
    except (TypeError,ValueError):return None


def number(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):return None


def initialize(state, now):
    r=state.setdefault('research',{})
    return r.setdefault('evaluation_v1',{'version':VERSION,'registered_at':now.isoformat(timespec='seconds'),
        'policy':{'train_closes':TRAIN_MIN,'validation_closes':TEST_MIN,
            'train_days':TRAIN_DAYS,'validation_days':TEST_DAYS,'daily_cluster_z':Z_FAMILY,
            'maximum_reports':MAX_REPORTS,'automatic_strategy_promotion':False},
        'reports':{},'status':'UNPROVEN','last_run':None})


def certified(state, key):
    e=(state.get('research') or {}).get('evaluation_v1') or {}
    return (e.get('version')==VERSION and e.get('reports',{}).get(key,{}).get('status')=='VALIDATED_OOS')


def cost_roi(t,cost):
    entry,exit_,nominal=(number(t.get(k)) for k in ['entry_price_usd','exit_price_usd','notional_gbp'])
    if entry is None or exit_ is None or nominal is None or entry<=0 or exit_<=0 or nominal<=0:return None
    return 100*((exit_/entry)*(1-cost)/(1+cost)-1)


def summarize(trades):
    """Keep nominal outcomes untouched; stress scenarios are explicitly separate."""
    daily=defaultdict(list)
    roi=[]
    for t in trades:
        value=number(t.get('roi_pct'));at=stamp(t.get('exit_at'))
        if value is not None and at:
            roi.append(value);daily[at.date().isoformat()].append(value)
    clusters=[sum(x)/len(x) for x in daily.values()]
    mean=sum(clusters)/len(clusters) if clusters else None
    se=(math.sqrt(sum((x-mean)**2 for x in clusters)/(len(clusters)-1)/len(clusters)) if len(clusters)>1 else None)
    stress={}
    for cost in (.01,.02,.05):
        values=[cost_roi(t,cost) for t in trades]
        stress[str(int(cost*100))+'pct_each_side_mean_roi_pct']=(round(sum(values)/len(values),4) if values and all(x is not None for x in values) else None)
    pnls=[number(t.get('net_pnl_gbp')) for t in trades]
    clean=[x for x in pnls if x is not None]
    return {'closed':len(trades),'days':len(daily),'wallets':len({t.get('wallet') for t in trades if t.get('wallet')}),
        'pools':len({t.get('token') for t in trades if t.get('token')}),
        'net_gbp':round(sum(clean),4),'net_excluding_best_gbp':round(sum(clean)-max([0]+clean),4),
        'daily_mean_roi_pct':round(mean,4) if mean is not None else None,
        'daily_cluster_lower_pct':round(mean-Z_FAMILY*se,4) if se is not None else None,
        'complete_outcomes':len(roi)==len(trades) and len(clean)==len(trades),
        'cost_stress':stress}


def evaluate(trades, registered_at, wallet=False):
    """Predeclare outcome-blind forward validation sampling to reach 7 days.

    Training stops on the first >=40 closes across >=14 distinct days.
    Validation then takes the smallest subsequent chronological prefix with
    >=20 closes on >=7 independent exit dates. This cures the old frozen-first-
    20 day-one trap; it does NOT let performance cherry-pick validation trades.
    A completed cohort freezes against late insertions / historical rewrites.
    """
    start=stamp(registered_at)
    unique={}
    for t in sorted(trades,key=lambda t:(t.get('exit_at',''),t.get('signal_id',''))):
        opened,exit_=stamp(t.get('opened_at')),stamp(t.get('exit_at'))
        sid=t.get('signal_id')
        if sid and start and opened and exit_ and start<=opened<exit_:
            unique.setdefault(sid,t)
    clean=list(unique.values())
    boundary=None
    for i in range(TRAIN_MIN,len(clean)+1):
        part=clean[:i]
        if len({stamp(t['exit_at']).date() for t in part})>=TRAIN_DAYS:
            boundary=i;break
    train=clean[:boundary] if boundary else clean
    cutoff=max((stamp(t['exit_at']) for t in train),default=None) if boundary else None
    validation_stream=[t for t in clean[boundary:]
                       if cutoff and stamp(t['opened_at'])>cutoff] if boundary else []
    # Fixed, predeclared rule: take earliest point with minimum observations
    # AND distinct dates. Do NOT choose a later boundary based on profit.
    # Until sufficient evidence exists the incomplete stream may extend;
    # once complete, later trades cannot alter this frozen prefix.
    validation_end=None
    for i in range(TEST_MIN,len(validation_stream)+1):
        dates={stamp(t['exit_at']).date() for t in validation_stream[:i]}
        if len(dates)>=TEST_DAYS:
            validation_end=i
            break
    test=validation_stream[:validation_end] if validation_end else validation_stream
    a,b=summarize(train),summarize(test)
    enough=(boundary is not None and validation_end is not None and len(test)>=TEST_MIN and b['days']>=TEST_DAYS
        and a['pools']>=3 and b['pools']>=3
        and (wallet or (a['wallets']>=8 and b['wallets']>=8)))
    valid=(enough and a['complete_outcomes'] and b['complete_outcomes']
        and all((x['daily_cluster_lower_pct'] or 0)>0 and x['net_excluding_best_gbp']>0 for x in (a,b))
        and b['cost_stress']['2pct_each_side_mean_roi_pct'] is not None
        and b['cost_stress']['2pct_each_side_mean_roi_pct']>0)
    return {'status':'VALIDATED_OOS' if valid else 'UNPROVEN','training':a,'validation':b,
        'validation_window_complete':bool(enough), 'validation_prefix_complete':validation_end is not None,
        'evidence_hash':hashlib.sha256(json.dumps(train+test,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        'training_ids':[t['signal_id'] for t in train], 'validation_ids':[t['signal_id'] for t in test],
        'cutoff':cutoff.isoformat() if cutoff else None,
        'reason':'Fixed forward split; approximate daily-cluster uncertainty; no causal claim',
        'automatic_strategy_promotion':False}


def update(state, now):
    from .adaptive import feature_buckets
    e=initialize(state,now);r=state['research']
    groups=defaultdict(list)
    for t in state.get('closed',[]):
        groups['actual:all'].append(t)
        groups['wallet:'+str(t.get('wallet'))].append(t)
        features=r.get('entry_features',{}).get(t.get('signal_id'))
        if features:
            for k in feature_buckets(features):groups['feature:'+k].append(t)
            for name,threshold in [('change_5m_pct',0),('change_1h_pct',0),('volume_1h_usd',100000)]:
                value=number(features.get(name))
                if value is not None:
                    groups['entry:'+name+(':'+str(threshold)+'+' if value>=threshold else ':below'+str(threshold))].append(t)
    for t in r.get('shadow_closed',[]):groups['v2:'+str(t.get('strategy'))].append(t)
    for t in r.get('whale_v3',{}).get('shadow_closed',[]):groups['v3:'+str(t.get('strategy'))].append(t)
    old=e.get('reports',{});reports={}
    # Fixed portfolio/feature/strategy classes before wallet reports; never pick best P&L.
    keys=sorted(groups,key=lambda k:(k.startswith('wallet:'),k))[:MAX_REPORTS]
    for key in keys:
        rep=evaluate(groups[key],e['registered_at'],wallet=key.startswith('wallet:'))
        prior=old.get(key,{})
        if prior.get('invalidated') or prior.get('validation_prefix_complete'):
            # Legacy first-20 prefixes that never crossed seven days are NOT
            # frozen, otherwise adding day-eight closes can never qualify.
            if (prior.get('invalidated') or rep['validation_ids']!=prior['validation_ids'] or rep['training_ids']!=prior.get('training_ids') or rep['evidence_hash']!=prior.get('evidence_hash')):
                rep['status']='UNPROVEN';rep['invalidated']=True;rep['reason']='Frozen cohort changed; independent review required'
        reports[key]=rep
    reasons=defaultdict(list)
    for trade in state.get('closed',[]):reasons[str(trade.get('exit_reason','unknown'))].append(trade)
    e['exit_diagnostics']={reason:summarize(ts) for reason,ts in reasons.items()}
    e['sampled_adverse_selection']={'tracked_entries':len(e.get('entry_paths',{})),
        'description':'Subsequent sampled quotes only; missed intracycle extremes and stop counterfactuals are unknown'}
    e.update(reports=reports,last_run=now.isoformat(timespec='seconds'),status='UNPROVEN',
        legacy_actual_summary=summarize(state.get('closed',[])),
        validated_reports=sum(x['status']=='VALIDATED_OOS' for x in reports.values()),
        positive_reinforcement_events=sum(str(x.get('to_tier','')).startswith('reinforced') for x in r.get('reinforcement_events',[])),
        sizing_policy='Positive increases require legacy safety gates AND registered out-of-sample validation. Negative controls retain priority.')
    return e


def observe_whales(r, flows, prices, now):
    """Later quoted outcomes of observed flows, not copied wallet profit."""
    pending=r.setdefault('flow_followups',[])
    done=r.setdefault('flow_outcomes',[])
    for item in list(pending):
        price=number(prices.get(item['token']));age=(now-stamp(item['observed_at'])).total_seconds()
        if price is None or price<=0:continue
        ret=100*(price/item['observation_price_usd']-1)
        item['mfe_pct']=max(item['mfe_pct'],ret);item['mae_pct']=min(item['mae_pct'],ret)
        for minute in (5,30,60):
            key=str(minute)+'m'
            if age>=minute*60 and key not in item['marks']:
                item['marks'][key]={'at':now.isoformat(timespec='seconds'),'quote_return_pct':round(ret,4)}
        if age>=3600:
            done.append(item);pending.remove(item)
    known={x['event_id'] for x in pending+done}
    for flow in flows:
        price=number(prices.get(flow['token']))
        if flow['event_id'] not in known and flow.get('fresh') and price is not None and price>0:
            pending.append({'event_id':flow['event_id'],'wallet':flow['wallet'],'token':flow['token'],
                'observed_at':now.isoformat(timespec='seconds'),'observation_price_usd':price,
                'kind':flow['kind'],'marks':{},'mfe_pct':0.,'mae_pct':0.,'wallet_profit_verified':False})
    r['flow_followups']=[x for x in pending if (now-stamp(x['observed_at'])).total_seconds()<=7200][-200:]
    r['flow_outcomes']=done[-500:]


def observe_positions(state,prices,now):
    e=initialize(state,now)
    paths=e.setdefault('entry_paths',{})
    registered=stamp(e['registered_at'])
    trades=state.get('positions',[])+state.get('research',{}).get('shadow_positions',[])
    for p in trades:
        opened=stamp(p.get('opened_at'));sid=p.get('signal_id')
        price=number(prices.get(p.get('token')));entry=number(p.get('entry_price_usd'))
        if not sid or not opened or opened<registered or price is None or price<=0 or not entry or entry<=0:continue
        key=str(p.get('strategy','actual'))+':'+sid
        sample=paths.setdefault(key,{'signal_id':sid,'strategy':p.get('strategy','actual'),
            'first_observed_at':now.isoformat(timespec='seconds'),'mfe_pct':0.,'mae_pct':0.,'samples':0})
        ret=100*(price/entry-1)
        sample.update(mfe_pct=round(max(sample['mfe_pct'],ret),4),mae_pct=round(min(sample['mae_pct'],ret),4),
            last_observed_at=now.isoformat(timespec='seconds'),samples=sample['samples']+1)
    e['entry_paths']=dict(list(paths.items())[-2000:])


def safe_update(state,now):
    """Research failures revoke positive certificates; never block account save."""
    try:
        return update(state,now)
    except Exception as exc:
        e=initialize(state,now)
        e.update(status='DEGRADED',reports={},validated_reports=0,
                 last_error=str(exc)[:180],last_run=now.isoformat(timespec='seconds'))
        return e
