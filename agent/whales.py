"""Whale-sized Solana swap-flow research, with forward-only PAPER shadow outcomes.

A large transaction is NOT proof of wallet wealth, ownership, investor identity,
profitability, or even that tx_from_address is the beneficial trading wallet.
No real trading / keys / exchanges / payments. Additive to existing V2 research.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from .shadow_retirement import update_retirements

VERSION = 3
USD_LARGE = 10_000.0
USD_VERY_LARGE = 50_000.0
MAX_EVENT_AGE_SECONDS = 240
DISCOVERY_PERIOD_CYCLES = 3
MAX_EXTRA_POOLS = 2
MAX_SHADOW_MARKS = 2
RESEARCH_TIME_BUDGET_SECONDS = 25
MAX_SHADOW_PER_STRATEGY = 2
MAX_TRACKED_SIGNALS = 1400
MAX_EVENT_IDS = 3500
MAX_HISTORY = 2000
MAX_CLOSES = 1200
MAX_IDENTITIES = 700
COST_SIDE = .01
UTC = dt.timezone.utc
STRATEGIES = ('large_repeat', 'very_large', 'accumulation')


def nfloat(value, default=None):
    try:
        f = float(value)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError, OverflowError):
        return default


def timestamp(value):
    if isinstance(value, dt.datetime):
        return value.astimezone(UTC) if value.tzinfo else None
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def initialize(state):
    research = state.setdefault('research', {})
    r = research.setdefault('whale_v3', {})
    r.setdefault('version', VERSION)
    r.setdefault('initialized_at', dt.datetime.now(UTC).isoformat(timespec='seconds'))
    r.setdefault('last_run', None)
    r.setdefault('status', 'INITIALISING')
    r.setdefault('errors', [])
    r.setdefault('last_scan_errors', [])
    r.setdefault('watched_pools', [])
    r.setdefault('recent_flows', [])
    r.setdefault('observed_ids', [])
    r.setdefault('sender_profiles', {})
    r.setdefault('sender_shadow_reports', {})
    r.setdefault('safety_cache', {})
    r.setdefault('shadow_positions', [])
    r.setdefault('shadow_closed', [])
    r.setdefault('shadow_reports', {})
    r.setdefault('shadow_sizing_events', [])
    r.setdefault('research_events', [])
    r.setdefault('shadow_mark_health', {})
    r.setdefault('shadow_sizing', {s: .005 for s in STRATEGIES})
    r.setdefault('scanner', {'additional_pools': 0, 'large_flows': 0, 'very_large_flows': 0, 'fresh_signals': 0})
    r.setdefault('owner_identity_verified', False)
    r.setdefault('methodology', 'Tx sender attribution unverified; whale-sized flow is not wallet wealth or holder identity. Only forward paper shadow outcomes count as performance evidence.')
    return r


def record_issue(r, issue):
    r['last_scan_errors'].append(str(issue)[:230])
    r['errors'].append({'at': dt.datetime.now(UTC).isoformat(timespec='seconds'), 'error': str(issue)[:230]})
    r['errors'] = r['errors'][-50:]


def fast_fetch(path, params=None, timeout=5):
    """At most one public GeckoTerminal request, never paid and never retried."""
    from .core import BASE, HEADERS
    url = BASE + path + ('?' + urllib.parse.urlencode(params) if params else '')
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or 'errors' in payload:
        raise ValueError('Invalid/errored GeckoTerminal response')
    return payload


def simple_report(trades):
    """Counts only closed forward paper shadow trades, and is net of 1% each side."""
    trades = [t for t in trades if nfloat(t.get('net_pnl_gbp')) is not None]
    n = len(trades)
    values = [float(x['net_pnl_gbp']) for x in trades]
    roi = [nfloat(x.get('roi_pct')) for x in trades]
    roi = [x for x in roi if x is not None]
    wins = sum(x > 0 for x in values)
    gross_w = sum(max(0., x) for x in values)
    gross_l = -sum(min(0., x) for x in values)
    avg = sum(roi)/len(roi) if roi else None
    margin = (1.96 * math.sqrt(sum((x-avg)**2 for x in roi)/(len(roi)-1))/math.sqrt(len(roi))) if len(roi)>1 else None
    best = max([0] + values)
    days = {timestamp(x.get('exit_at')).date().isoformat() for x in trades if timestamp(x.get('exit_at'))}
    signals = {x.get('signal_id') for x in trades if x.get('signal_id')}
    wallets = {x.get('wallet') for x in trades if x.get('wallet')}
    pools = {x.get('token') for x in trades if x.get('token')}
    mints = {x.get('signal_features', {}).get('mint') for x in trades
             if isinstance(x.get('signal_features'),dict) and x['signal_features'].get('mint')}
    alt_costs={}
    for cost in (.02, .05):
        net=0.0
        for trade in trades:
            entry=nfloat(trade.get('entry_price_usd'))
            exit_=nfloat(trade.get('exit_price_usd'))
            notional=nfloat(trade.get('notional_gbp'))
            if not entry or not exit_ or notional is None:continue
            net+=notional*exit_/entry*(1-cost)-notional*(1+cost)
        alt_costs[f'net_gbp_at_{int(cost*100)}pct_each_side']=round(net,4)
    return {
        **alt_costs,
        'closed': n, 'wins': wins, 'losses': n-wins,
        'win_rate_pct': round(100*wins/n, 2) if n else None,
        'net_gbp': round(sum(values),4),
        'mean_roi_pct': round(avg,3) if avg is not None else None,
        'lower_mean_roi_95_pct': round(avg-margin,3) if margin is not None else None,
        'profit_factor': round(gross_w/gross_l,3) if gross_l else None,
        'net_excluding_best_gbp': round(sum(values)-best,4),
        'distinct_days': len(days), 'distinct_wallets': len(wallets),
        'distinct_pools': len(pools), 'distinct_mints': len(mints),
        'distinct_signals': len(signals),
    }


def strong_evidence(report):
    """No auto-promotion from cherry-picked whale-sized trades."""
    return (report['closed'] >= 40 and report['distinct_days'] >= 14
            and report['distinct_wallets'] >= 10 and report['distinct_pools'] >= 5
            and report['distinct_mints'] >= 3
            and report['distinct_signals'] == report['closed']
            and report['net_gbp'] > 0 and report['net_excluding_best_gbp'] > 0
            and ((report['profit_factor'] or 0) >= 1.35 or (report['wins'] == report['closed'] and report['wins'] > 0))
            and report['lower_mean_roi_95_pct'] is not None
            and report['lower_mean_roi_95_pct'] > 0)


def _dedup_flows(state, base_events, extra_events, now, extra_meta):
    """Dedup against persisted whale history (not the separate core seen list)."""
    r=initialize(state)
    seen = set(r['observed_ids'])
    flows=[]
    age_limit = dt.timedelta(hours=2)
    latest = timestamp(now)
    for event, source in [(ev, 'core_candidates') for ev in base_events] + [(ev,'extra_pool') for ev in extra_events]:
        stamp = timestamp(event.get('timestamp'))
        amount = nfloat(event.get('usd'))
        if not stamp or amount is None or amount < USD_LARGE or not event.get('wallet') or not event.get('token'):
            continue
        identifier = event.get('id')
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        age=(latest-stamp).total_seconds()
        # Historical observations may inform discovery, never hypothetical backfilled profits.
        flows.append({'event_id':identifier,'at':stamp.isoformat(timespec='seconds'),
                      'wallet':event['wallet'],'token':event['token'],
                      'pool_name':event.get('pool_name'),'kind':event.get('kind'),
                      'usd':round(amount,2),'source':source,'fresh':0<=age<=MAX_EVENT_AGE_SECONDS and not event.get('research_only',False),
                      'transaction_hash':str(identifier).split(':',1)[0],
                      'age_seconds':round(age,1),
                      'size_tier':'VERY_LARGE_FLOW' if amount>=USD_VERY_LARGE else 'LARGE_FLOW',
                      'sender_identity':'UNVERIFIED_TX_FROM_ADDRESS · aggregator/owner unresolved'})
    r['observed_ids'] = (r['observed_ids']+[f['event_id'] for f in flows])[-MAX_EVENT_IDS:]
    r['recent_flows'] = ([f for f in r['recent_flows'] if timestamp(f.get('at')) and latest-timestamp(f.get('at'))<=age_limit]+flows)[-MAX_HISTORY:]
    for f in flows:
        wallet=f['wallet']
        p=r['sender_profiles'].setdefault(wallet, {'buys':0,'sells':0,'buy_volume_usd':0.,'sell_volume_usd':0.,'pools':[],'last_seen':None,'identity_verified':False})
        side=f['kind']
        if side not in ('buy','sell'):continue
        p[side+'s']+=1
        p[side+'_volume_usd']=round(p[side+'_volume_usd']+f['usd'],2)
        p['last_seen']=f['at']
        if f['token'] not in p['pools']:p['pools']=(p['pools']+[f['token']])[-12:]
    if len(r['sender_profiles'])>MAX_IDENTITIES:
        ordered=sorted(r['sender_profiles'],key=lambda w:r['sender_profiles'][w].get('last_seen') or '',reverse=True)
        r['sender_profiles']={w:r['sender_profiles'][w] for w in ordered[:MAX_IDENTITIES]}
    return flows


def _observe_activity(r,events,now):
    # Sampled transaction-origin behaviour, never beneficial-owner attribution.
    seen=set(r.get('activity_seen',[]));profiles=r.setdefault('sampled_activity',{})
    for ev in events:
        sid=ev.get('id');wallet=ev.get('wallet');at=timestamp(ev.get('timestamp'))
        if not sid or sid in seen or not wallet or not at or not 0<=(now-at).total_seconds()<=7200:continue
        seen.add(sid)
        p=profiles.setdefault(wallet,{'buys':0,'sells':0,'pools':[],'last_seen':None,'identity_verified':False})
        if ev.get('kind') not in ('buy','sell'):continue
        p[ev['kind']+'s']+=1
        p['last_seen']=max(p.get('last_seen') or '',at.isoformat(timespec='seconds'))
        if ev['token'] not in p['pools']:p['pools']=(p['pools']+[ev['token']])[-12:]
        p['attribution']='MULTI_POOL_OR_ROUTER_POSSIBLE' if len(p['pools'])>=3 else 'UNVERIFIED_TRANSACTION_ORIGIN'
        p['two_sided_activity']=bool(p['buys'] and p['sells'])
    r['activity_seen']=list(dict.fromkeys([*r.get('activity_seen',[]),*[ev['id'] for ev in events if ev.get('id') in seen]]))[-3500:]
    r['sampled_activity']=dict(sorted(profiles.items(),key=lambda x:x[1].get('last_seen') or '',reverse=True)[:700])


def candidates_from_flows(r, flows, now):
    """Choose only *current* fresh buys; count preceding distinct buys for evidence."""
    recent=r['recent_flows']
    result=[]
    for flow in flows:
        if flow['kind']!='buy' or not flow['fresh']:
            continue
        window=[]
        for x in recent:
            when=timestamp(x.get('at'))
            lag=(timestamp(now)-when).total_seconds() if when else float('inf')
            if x['wallet']==flow['wallet'] and x['token']==flow['token'] and 0<=lag<=2700:
                window.append(x)
        buys=[x for x in window if x['kind']=='buy']
        sells=[x for x in window if x['kind']=='sell']
        buy_total=sum(x['usd'] for x in buys)
        sell_total=sum(x['usd'] for x in sells)
        sell_in_current=any(x['fresh'] and x['event_id']!=flow['event_id'] for x in sells)
        strategies=[]
        if flow['usd']>=USD_VERY_LARGE: strategies.append('very_large')
        if len({x['event_id'] for x in buys})>=2 and buy_total>=20_000 and not sell_in_current:
            strategies.append('large_repeat')
        if len({x['event_id'] for x in buys})>=3 and (buy_total-sell_total)>=30_000 and sell_total < buy_total*.25 and not sell_in_current:
            strategies.append('accumulation')
        for name in strategies:
            result.append({**flow,'strategy':name,'buys_45m':len(buys),
                           'sells_45m':len(sells),'buy_volume_45m_usd':round(buy_total,2),
                           'sell_volume_45m_usd':round(sell_total,2),
                           'net_buy_45m_usd':round(buy_total-sell_total,2)})
    return result


def risk_allowed(r, mint, now, screener):
    # Fail closed. Never trust cached PASS beyond 15 minutes.
    prev=r['safety_cache'].get(mint)
    at=timestamp(prev.get('at')) if isinstance(prev,dict) else None
    if at and 0 <= (now-at).total_seconds()<900:
        if prev.get('status') == 'UNAVAILABLE':
            issue='security provider unavailable for '+str(mint)[:44]
            if issue not in r['last_scan_errors']: record_issue(r,issue)
        return prev.get('status')=='PASS'
    try:
        check=screener(mint)
        if isinstance(check,dict):
            status=check.get('status')
            if status not in ('PASS','REJECTED','UNAVAILABLE') or ((status=='PASS') != (check.get('allowed') is True)):
                status='UNAVAILABLE'
            allowed=status=='PASS'
        elif isinstance(check,bool):
            allowed=check
            status='PASS' if allowed else 'REJECTED'
        else:
            allowed=False
            status='UNAVAILABLE'
        if status=='UNAVAILABLE': record_issue(r,'security provider unavailable for '+str(mint)[:44])
    except Exception as exc:
        record_issue(r,'risk screening failed: '+str(exc)[:100])
        allowed=False
        status='UNAVAILABLE'
    r['safety_cache'][mint]={'status':status,'at':now.isoformat(timespec='seconds')}
    if len(r['safety_cache'])>80:
        r['safety_cache']=dict(list(r['safety_cache'].items())[-80:])
    return allowed


def _close(r,pos,price,now,reason):
    if price is None or price<=0:return
    # Round-trip model uses the same adverse fee/slippage rate as the original account.
    proceeds=pos['notional_gbp']*price/pos['entry_price_usd']*(1-COST_SIDE)
    pnl=proceeds-pos['cost_gbp']
    outcome={**pos,'exit_at':now.isoformat(timespec='seconds'),'exit_price_usd':price,
             'exit_reason':reason,'proceeds_gbp':round(proceeds,4),
             'net_pnl_gbp':round(pnl,4),'roi_pct':round(100*pnl/pos['cost_gbp'],3)}
    r['shadow_closed'].append(outcome)
    r['shadow_closed']=r['shadow_closed'][-MAX_CLOSES:]
    r['shadow_positions'].remove(pos)
    r['research_events'].append({'at':now.isoformat(timespec='seconds'),
                                  'action':'WHALE_SHADOW_CLOSE','strategy':pos['strategy'],
                                  'wallet':pos['wallet'],'token':pos['token'],
                                  'pnl_gbp':outcome['net_pnl_gbp'],'reason':reason})


def _mark_open(r,prices,events,now):
    sells={(x['wallet'],x['token']) for x in events if x['kind']=='sell' and x['fresh']}
    r['shadow_mark_health']={}
    for pos in list(r['shadow_positions']):
        price=nfloat(prices.get(pos['token']))
        if price is None or price<=0:
            r['shadow_mark_health'][pos['token']]='UNPRICED'
            pos['last_mark_price_usd']=None
            record_issue(r,'unpriced whale shadow '+str(pos['token'])[:44])
            continue
        age=(now-timestamp(pos['opened_at'])).total_seconds()/3600
        roi=100*((price/pos['entry_price_usd'])*(1-COST_SIDE)/(1+COST_SIDE)-1)
        reason=('observed sell' if (pos['wallet'],pos['token']) in sells else
                '12% paper stop' if roi<=-12 else '20% paper target' if roi>=20 else
                '6h shadow limit' if age>=6 else None)
        if reason:_close(r,pos,price,now,reason)
        else:pos['last_mark_price_usd']=price


def _update_reports(r, now):
    by=defaultdict(list)
    for closed in r['shadow_closed']:
        if closed.get('strategy') in STRATEGIES: by[closed['strategy']].append(closed)
    for name in STRATEGIES:
        report=simple_report(by[name])
        validation=(r.get('oos_validation') or {}).get(name,False)
        evidence=strong_evidence(report) and validation
        old=r['shadow_sizing'].get(name,.005)
        # Shadow account only! This NEVER changes real simulated £2k positions.
        new=.0075 if evidence else .005
        if new!=old:
            r['shadow_sizing_events'].append({'at':now.isoformat(timespec='seconds'),'strategy':name,
                 'previous':old,'new':new,'reason':'EVIDENCE_GATED_SHADOW_ONLY' if evidence else 'REVERT_INSUFFICIENT_EVIDENCE',
                 'closures':report['closed']})
        r['shadow_sizing'][name]=new
        report['open_positions']=sum(x['strategy']==name for x in r['shadow_positions'])
        report['status']='SHADOW_REINFORCED' if evidence else 'COLLECTING_EVIDENCE'
        report['allocation_fraction_of_original_equity']=new
        report['paper_account_promoted']=False
        r['shadow_reports'][name]=report
    update_retirements(r,r['shadow_reports'],now,event_key='research_events',
                       event_action='WHALE_SHADOW_STRATEGY_RETIRED')
    r['shadow_sizing_events']=r['shadow_sizing_events'][-80:]
    # A wallet may produce the same signal in multiple experimental strategies.
    # Do not count those correlated outcomes as independent wallet successes.
    grouped=defaultdict(dict)
    for result in r['shadow_closed']:
        wallet=result.get('wallet')
        signal_id=result.get('signal_id')
        if wallet and signal_id and signal_id not in grouped[wallet]:
            grouped[wallet][signal_id]=result
    scores={}
    for wallet, signals in grouped.items():
        report=simple_report(list(signals.values()))
        credible=(report['closed']>=10 and report['distinct_days']>=3
                  and report['distinct_pools']>=2 and report['net_excluding_best_gbp']>0
                  and report['lower_mean_roi_95_pct'] is not None
                  and report['lower_mean_roi_95_pct']>0
                  and (report['profit_factor'] or (float('inf') if report['wins']==report['closed'] else 0))>=1.3)
        report.update(status='POSITIVE_FORWARD_SHADOW_EVIDENCE' if credible else 'COLLECTING_EVIDENCE',
                      identity_verified=False, eligible_for_real_paper_sizing=False)
        scores[wallet]=report
    ordered=sorted(scores,key=lambda wallet:(scores[wallet]['closed'],scores[wallet]['net_gbp']),reverse=True)
    r['sender_shadow_reports']={wallet:scores[wallet] for wallet in ordered[:MAX_IDENTITIES]}


def _pick_watchlist(state, fetch, r, discovered=None):
    # Reuse the full primary discovery page. Rotate pages 2–5, rather than
    # repeatedly querying the same two pools. Inventory is observational only.
    from .core import pool_meta, eligible
    registry=r.setdefault('pool_registry', {})
    cycle=state.get('completed_cycles',0)
    for meta in discovered or []:
        if eligible(meta):registry[meta['pool']]=meta
    due=cycle%DISCOVERY_PERIOD_CYCLES==0 or not r['watched_pools']
    if due:
        page=2+(r.get('discovery_rotation',0)%4)
        try:
            payload=fetch('/networks/solana/trending_pools', {'page':page,'include':'base_token'})
            arr=payload.get('data')
            if not isinstance(arr,list):raise ValueError('Supplemental trending-pool feed is malformed')
            for raw in arr:
                meta=pool_meta(raw)
                if eligible(meta):registry[meta['pool']]=meta
            r['discovery_rotation']=r.get('discovery_rotation',0)+1
        except Exception as exc:
            record_issue(r,'extra pool discovery: '+str(exc))
    for meta in r['watched_pools']:
        registry.setdefault(meta['pool'],meta)
    original={m.get('pool') for m in state.get('watched_pools',[])}
    held={p['token'] for p in r['shadow_positions']}
    active={f['token'] for f in r['recent_flows'] if f.get('fresh')}
    scans=r.setdefault('pool_last_scanned',{})
    items=[m for m in registry.values() if m['pool'] not in original and eligible(m)]
    items.sort(key=lambda m:(m['pool'] not in held, m['pool'] not in active, scans.get(m['pool'],''),m['pool']))
    r['watched_pools']=items[:MAX_EXTRA_POOLS]
    # Keep active holdings plus recent inventory; bounds remain small on Actions.
    keep=list(dict.fromkeys([*held,*[m['pool'] for m in items],*registry]))[:64]
    r['pool_registry']={k:registry[k] for k in keep if k in registry}
    r['pool_last_scanned']={k:v for k,v in scans.items() if k in r['pool_registry']}


def whale_cycle(state, candidate_pools, new_events, prices, current, *, fetch=None, screener=None, previous_run=None, discovered=None):
    """Separate, bounded market research; *only* mutates research.whale_v3.

    Uses existing candidate flows plus extra pools. Extra fetches never retry and
    never block core failure policy. All calls are bounded and optional.
    """
    from . import core
    now=timestamp(current)
    if now is None:raise ValueError('timezone-aware cycle timestamp required')
    r=initialize(state)
    r['last_scan_errors']=[]
    r['scan_metrics']={'quote_pools':0,'trade_feeds':0}
    r['last_quotes']={}
    budget_started = time.monotonic()
    # Reuse the core cycle's recently completed security checks.
    # V3 never overrides the main paper account's safety verdict.
    for verdict in state.get('screening', []):
        mint=verdict.get('mint') if isinstance(verdict,dict) else None
        if mint:
            status=verdict.get('status')
            if status in ('PASS','REJECTED','UNAVAILABLE'):
                r['safety_cache'][mint]={'at':now.isoformat(timespec='seconds'),'status':status}
    prior=timestamp(previous_run if previous_run is not None else state.get('last_run'))
    production = fetch is None or fetch is core.api
    if production:
        from .research_feed import ResearchFeed
        fetch=ResearchFeed(r,now)
        # The optional primary-window pause precedes the 25s research budget.
        # Freshness is evaluated at actual research observation time.
        now=dt.datetime.now(UTC)
        budget_started=time.monotonic()
    if screener is None:
        from .safety import inspect_token
        screener=inspect_token
    meta={p['pool']:p for p in candidate_pools if p.get('pool')}
    extra_events=[]
    try:
        _pick_watchlist(state,fetch,r,discovered)
    except Exception as exc:
        record_issue(r,'extra pool discovery: '+str(exc))
    watch=r['watched_pools'][:MAX_EXTRA_POOLS]
    # Independent pool quotes; do not use 15-minute-old pool meta as executable current quotes.
    if watch:
        addrs=','.join(urllib.parse.quote(x['pool'],safe='') for x in watch)
        try:
            try:
                detail=fetch('/networks/solana/pools/multi/'+addrs,{'include':'base_token'})
            except Exception as primary_error:
                if not production:raise
                r['scan_metrics']['quote_primary_error']=str(primary_error)[:160]
                detail=fetch.fallback_quotes([x['pool'] for x in watch])
            feed=detail.get('data')
            if not isinstance(feed,list):raise ValueError('multi-pool response not a list')
            for raw in feed:
                m=core.pool_meta(raw)
                if core.eligible(m) and m['pool'] in {x['pool'] for x in watch}:
                    meta[m['pool']]=m
                    if nfloat(m['price_usd'],0)>0:
                        prices[m['pool']]=m['price_usd']
                        observed_at=dt.datetime.now(UTC).isoformat(timespec='seconds')
                        r['last_quotes'][m['pool']]={'at':observed_at,'price_usd':m['price_usd'],'mint':m['mint']}
                        r['last_market_data_at']=observed_at
                        r['scan_metrics']['quote_pools']=len(r['last_quotes'])
        except Exception as exc:
            record_issue(r,'extra quotes: '+str(exc))
    for pool in watch:
        # A persisted pool may still have eligible *historical* metadata.
        # Only the current scan's accepted supplemental quote proves that it
        # remains observable. Prioritise genuinely untried pools next cycle
        # instead of repeatedly burning a slot on an unquoted pool.
        if pool['pool'] not in r['last_quotes']:
            r.setdefault('pool_last_scanned',{})[pool['pool']]=now.isoformat(timespec='seconds')
            record_issue(r,'fresh supplemental quote missing for '+pool['pool'][:44])
    # Mark older whale shadow positions (possibly no longer on the supplemental watchlist).
    missing=[p['token'] for p in r['shadow_positions'] if p['token'] not in prices]
    for token in list(dict.fromkeys(missing))[:MAX_SHADOW_MARKS]:
        if time.monotonic()-budget_started >= RESEARCH_TIME_BUDGET_SECONDS:
            record_issue(r,'V3 research time budget reached before shadow mark');break
        try:
            detail=fetch('/networks/solana/pools/'+urllib.parse.quote(token,safe=''),{'include':'base_token'})
            m=core.pool_meta(detail.get('data') or {})
            if nfloat(m.get('price_usd'),0)>0:prices[token]=m['price_usd']
        except Exception as exc:
            record_issue(r,'shadow quote '+token[:12]+': '+str(exc))
    for pool in watch:
        if time.monotonic()-budget_started >= RESEARCH_TIME_BUDGET_SECONDS:
            record_issue(r,'V3 research time budget reached before extra swap scan');break
        if pool['pool'] not in r['last_quotes']:continue  # no unpriced/stale supplemental trades
        try:
            r.setdefault('pool_last_scanned',{})[pool['pool']]=now.isoformat(timespec='seconds')
            path='/networks/solana/pools/'+urllib.parse.quote(pool['pool'],safe='')+'/trades'
            response=fetch(path,{'trade_volume_in_usd_greater_than':core.MIN_TRADE_USD if hasattr(core,'MIN_TRADE_USD') else 100})
            if not isinstance(response.get('data'),list):raise ValueError('extra trade feed missing list')
            r['scan_metrics']['trade_feeds']+=1
            r['last_market_data_at']=dt.datetime.now(UTC).isoformat(timespec='seconds')
            for raw in response['data']:
                event=core.extract_event(raw,meta[pool['pool']])
                if event:
                    stamp=timestamp(event['timestamp'])
                    if stamp and 0 <= (now-stamp).total_seconds() <= 7200:
                        event['research_only']=not (prior and prior<stamp<=now and (now-stamp).total_seconds()<=MAX_EVENT_AGE_SECONDS)
                        extra_events.append(event)
        except Exception as exc:
            record_issue(r,'extra trades '+pool['pool'][:12]+': '+str(exc))
    flows=_dedup_flows(state,new_events,extra_events,now,meta)
    # Observe even smaller sells from the core feed when managing whale shadows.
    # This reduces conflict/churn, even though small trades are not whale-sized discoveries.
    seen_sells=[{'wallet':e['wallet'],'token':e['token'],'kind':'sell','fresh':True}
                for e in [*new_events,*extra_events] if e.get('kind')=='sell' and not e.get('research_only',False)]
    _mark_open(r,prices,flows+seen_sells,now)
    retirement_reports={name:simple_report([t for t in r['shadow_closed'] if t.get('strategy')==name])
                        for name in STRATEGIES}
    update_retirements(r,retirement_reports,now,event_key='research_events',
                       event_action='WHALE_SHADOW_STRATEGY_RETIRED')
    _observe_activity(r,[*new_events,*extra_events],now)
    from .evaluation import observe_whales
    observe_whales(r,flows,prices,now)
    chosen=candidates_from_flows(r,flows,now)
    conflicting={(f['wallet'],f['token']) for f in flows+seen_sells if f['kind']=='sell' and f['fresh']}
    for signal in chosen:
        if time.monotonic()-budget_started >= RESEARCH_TIME_BUDGET_SECONDS:
            record_issue(r,'V3 research time budget reached before shadow entry screening');break
        token=signal['token'];wallet=signal['wallet'];name=signal['strategy']
        if name in r.get('retired_shadow_strategies',{}):continue
        if (wallet,token) in conflicting:continue
        m=meta.get(token)
        if not m or not core.eligible(m):continue
        price=nfloat(prices.get(token))
        if price is None or price<=0:continue
        prior_positions=[p for p in r['shadow_positions'] if p['strategy']==name]
        if len(prior_positions)>=MAX_SHADOW_PER_STRATEGY:continue
        if any(p['wallet']==wallet or p['token']==token for p in prior_positions):continue
        if any(p['strategy']==name and p['wallet']==wallet and p['token']==token and
               timestamp(p.get('exit_at')) and
               0<=(now-timestamp(p['exit_at'])).total_seconds()<1800
               for p in r['shadow_closed'][-50:]):continue
        if not risk_allowed(r,m['mint'],now,screener):continue
        # Original paper capital is read-only: this is an independent notional simulation.
        fraction=min(.015,r['shadow_sizing'].get(name,.005))
        nominal=round(float(state.get('starting_gbp',2000))*fraction,2)
        if nominal<=0:continue
        pos=dict(strategy=name,wallet=wallet,token=token,pool_name=m.get('name'),
                 signal_id=signal['event_id'],source=signal['source'],
                 opened_at=now.isoformat(timespec='seconds'),signal_at=signal['at'],
                 entry_price_usd=price, last_mark_price_usd=price,
                 cost_gbp=round(nominal*(1+COST_SIDE),6),notional_gbp=nominal,
                 signal_features={**signal,'mint':m['mint'],
                                  'liquidity_usd':m['liquidity_usd'],
                                  'volume_24h_usd':m['volume_24h_usd'],
                                  'change_24h_pct':m.get('change_24h_pct'),
                                  'token_safety':'PASS','wallet_identity_verified':False})
        r['shadow_positions'].append(pos)
        r['research_events'].append({'at':now.isoformat(timespec='seconds'),
                                     'action':'WHALE_SHADOW_OPEN','strategy':name,
                                     'wallet':wallet,'token':token,'transaction_usd':signal['usd']})
    r['scanner']['inventory_pools']=len(r.get('pool_registry',{}))
    r['scanner']['additional_pools']=len(watch)
    r['scanner']['large_flows']+=len(flows)  # includes every event >= $10k
    r['scanner']['very_large_flows']+=sum(f['size_tier']=='VERY_LARGE_FLOW' for f in flows)
    r['scanner']['fresh_signals']+=sum(f['fresh'] for f in flows)
    r['research_events']=r['research_events'][-250:]
    from .evaluation import certified
    r['oos_validation']={name:certified(state,'v3:'+name) for name in STRATEGIES}
    _update_reports(r,now)
    r['last_run']=now.isoformat(timespec='seconds')
    r['scan_metrics']['elapsed_seconds']=round(time.monotonic()-budget_started,3)
    r['status']='DEGRADED' if r['last_scan_errors'] else 'OK'
    return r
