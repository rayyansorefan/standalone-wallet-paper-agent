"""Deterministic, paper-only wallet discovery and copied-trade simulator.

No wallet signing, private keys, trading/exchange APIs, or live execution code.
"""
from __future__ import annotations
import datetime as dt
import json
import math
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

STATE = pathlib.Path(os.getenv('PAPER_STATE', 'state/state.json'))
INITIAL_GBP = 2000.00
BASE = 'https://api.geckoterminal.com/api/v2'
HEADERS = {'Accept': 'application/json;version=20230203', 'User-Agent': 'ResearchPaperWalletAgent/1.0 (paper-only)'}
SOL_ADDRESS = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
# price-only model: 1% modeled adverse slippage+fees each side; no FX movements modeled.
COST_PER_SIDE = 0.01
MIN_LIQUIDITY_USD = 100_000.0
MIN_VOLUME_24H_USD = 150_000.0
MAX_TRADE_AGE_SECONDS = 240
# Two rotating on-chain swap feeds per five-minute production cycle (free quota).
MAX_MAIN_TRADE_FEEDS_PER_CYCLE = 2
MAX_OPEN = 5
MAX_HOLD_HOURS = 6.0
MIN_WALLET_SEEN = 3
MIN_TRADE_USD = 100.0
UTC = dt.timezone.utc
_PRIMARY_FEED = None


def now_iso():
    return dt.datetime.now(UTC).isoformat(timespec='seconds')


def parse_time(v):
    if not v: return None
    try: 
        parsed=dt.datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (TypeError, ValueError): return None


def safe_float(v):
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError, OverflowError): return None


def api(path, params=None):
    uri = BASE + path + ('?' + urllib.parse.urlencode(params) if params else '')
    req = urllib.request.Request(uri, headers=HEADERS)
    from .primary_feed import PrimaryFeed
    feed = _PRIMARY_FEED or PrimaryFeed({})
    for attempt in range(3):
        try:
            return feed.read(req)
        except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as exc:
            # Expired persisted cooldowns must not turn an unrelated transient
            # JSON/network error into a false rate-limit report. Only an actual
            # HTTP 429 or an ACTIVE cooldown is a non-retryable rate limit.
            retry_at=parse_time(feed.health.get('retry_at'))
            active_cooldown=bool(retry_at and retry_at>dt.datetime.now(UTC))
            if getattr(exc,'code',None)==429 or active_cooldown:
                raise RuntimeError(f'Primary rate limit for {path}: {exc}; retry at {feed.health.get("retry_at")}') from exc
            if 'budget exhausted' in str(exc):raise
            if attempt == 2: raise RuntimeError(f'API unavailable for {path}: {exc}') from exc
            time.sleep(2 ** attempt)


def blank_state():
    return dict(schema=1, paper_only=True, initialized_at=now_iso(), last_run=None, cash_gbp=INITIAL_GBP,
                starting_gbp=INITIAL_GBP, last_status='FIRST_RUN_PENDING', last_data_at=None, completed_cycles=0, stale_signals=0, unattributed_events=0, seen_trades=[],
                observed={}, positions=[], closed=[], decisions=[], snapshots=[], watched_pools=[], errors=[])


def load(path=STATE):
    if not path.exists(): return blank_state()
    data = json.loads(path.read_text(encoding='utf8'))
    if data.get('schema') != 1 or data.get('paper_only') is not True:
        raise ValueError('State does not belong to paper engine schema v1')
    return data


def save(data, path=STATE):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf8')
    temp.replace(path)


def log_decision(state, action, wallet=None, token=None, reason='', **extra):
    record = dict(at=now_iso(), action=action, wallet=wallet, token=token, reason=reason, **extra)
    state['decisions'].append(record)
    state['decisions'] = state['decisions'][-400:]


def wallet_stats(state, wallet):
    from .adaptive import wallet_report
    return wallet_report(state, wallet)


def wallet_risk_fraction(stats):
    from .adaptive import wallet_risk_fraction as adaptive_risk_fraction
    return adaptive_risk_fraction(stats)


def pool_meta(p):
    a = p.get('attributes') or {}
    liquidity = safe_float(a.get('reserve_in_usd')) or 0
    v = a.get('volume_usd') or {}
    volume = safe_float(v.get('h24')) or 0
    change = a.get('price_change_percentage') or {}
    h24_change = safe_float(change.get('h24'))
    token_price = safe_float(a.get('base_token_price_usd'))
    creation = parse_time(a.get('pool_created_at'))
    age_hours = (dt.datetime.now(UTC)-creation).total_seconds()/3600 if creation else None
    # The pool ADDRESS is not the token MINT. Follow the pool's base-token relationship.
    rel = (((p.get('relationships') or {}).get('base_token') or {}).get('data') or {})
    token_id = str(rel.get('id') or '')
    mint = token_id.split('_', 1)[1] if token_id.startswith('solana_') else ''
    if not SOL_ADDRESS.fullmatch(mint): mint = ''
    return dict(id=str(p.get('id') or ''), name=a.get('name') or 'Unknown', mint=mint,
                pool=str(a.get('address') or (str(p.get('id') or '').split('_', 1)[-1])),
                liquidity_usd=liquidity, volume_24h_usd=volume, price_usd=token_price,
                change_24h_pct=h24_change, age_hours=age_hours)


def eligible(m):
    # Reject incomplete/malformed prices, brand-new pools and dangerously shallow liquidity.
    return (m['liquidity_usd'] >= MIN_LIQUIDITY_USD and m['volume_24h_usd'] >= MIN_VOLUME_24H_USD
            and m['price_usd'] is not None and m['price_usd'] > 0
            and m['age_hours'] is not None and m['age_hours'] >= 24
            and m['pool'] and m['pool'] != 'None' and bool(m['mint']))


def extract_event(raw, pool):
    a = raw.get('attributes') or {}
    wallet = a.get('tx_from_address')
    kind = str(a.get('kind') or '').lower()
    ts = parse_time(a.get('block_timestamp'))
    usd = safe_float(a.get('volume_in_usd'))
    # The historical trade price is not an executable quote. Entry always uses the
    # current observed pool quote (with adverse modeled costs).
    txid = str(a.get('tx_hash') or raw.get('id') or '')
    if (not isinstance(wallet, str) or not SOL_ADDRESS.fullmatch(wallet) or not txid
            or kind not in {'buy','sell'} or not ts or not usd or usd < MIN_TRADE_USD): return None
    return dict(id=txid + ':' + kind + ':' + pool['pool'], wallet=wallet, kind=kind,
                usd=usd, timestamp=ts, token=pool['pool'], pool_name=pool['name'])


def equity(state, prices):
    total = state['cash_gbp']
    for pos in state['positions']:
        price = prices.get(pos['token'])
        if price and price > 0:
            total += pos['notional_gbp'] * price / pos['entry_price_usd'] * (1 - COST_PER_SIDE)
        else:
            return None  # never invent a missing mark-to-market price
    return round(total, 2)


def close_position(state, pos, price, reason):
    if not price or price <= 0: return False
    gross = pos['notional_gbp'] * price / pos['entry_price_usd']
    proceeds = gross * (1-COST_PER_SIDE)
    pnl = proceeds - pos['cost_gbp']
    record = dict(**pos, exit_at=now_iso(), exit_price_usd=price, exit_reason=reason,
                  proceeds_gbp=round(proceeds, 4), net_pnl_gbp=round(pnl, 4),
                  roi_pct=round(100*pnl/pos['cost_gbp'], 3))
    state['cash_gbp'] = round(state['cash_gbp'] + proceeds, 6)
    state['positions'].remove(pos)
    state['closed'].append(record)
    state['closed'] = state['closed'][-5000:]
    log_decision(state, 'CLOSE', pos['wallet'], pos['token'], reason, net_pnl_gbp=record['net_pnl_gbp'])
    return True


def maybe_open(state, ev, price, current, prices):
    wallet = ev['wallet']; token = ev['token']
    reason = None
    from .decision import entry_assessment
    assessment = entry_assessment(state, ev, current)
    if assessment is not None and not assessment['allowed']:
        log_decision(state, 'SKIP_POLICY', wallet, token, '; '.join(assessment['reasons']), assessment=assessment)
        return
    ws = wallet_stats(state, wallet)
    if ws['seen'] < MIN_WALLET_SEEN: reason = 'wallet has fewer than 3 observed qualifying trades'
    elif len(state['positions']) >= MAX_OPEN: reason = 'portfolio position limit'
    elif any(x['wallet'] == wallet for x in state['positions']): reason = 'one position per wallet'
    elif any(x['token'] == token for x in state['positions']): reason = 'one position per pool'
    elif any(x['wallet'] == wallet and x['token'] == token and
             (current-(parse_time(x['exit_at']) or current)).total_seconds() < 1800 for x in state['closed'][-50:]):
        reason = '30-minute cooldown'
    alloc_fraction = wallet_risk_fraction(ws)
    from .adaptive import feature_risk_multiplier
    feature_weight, feature_reason = feature_risk_multiplier(state, ev)
    if assessment and assessment.get('news',{}).get('status') == 'PARTIAL':
        feature_weight *= 0.5
        feature_reason += '; partial news coverage halves exploration allocation'
    alloc_fraction = min(0.015, alloc_fraction * feature_weight)
    if alloc_fraction == 0: reason = 'risk-adjusted trader score below threshold'
    eq = equity(state, prices)
    if eq is None:
        log_decision(state, 'SKIP', wallet, token, 'unpriced open position; unable to assess true equity')
        return
    alloc = min(round(eq*alloc_fraction, 2), round(state['cash_gbp']*0.98, 2))
    if alloc < 3.0: reason = 'insufficient available paper cash'
    if reason:
        log_decision(state, 'SKIP', wallet, token, reason, wallet_stats=ws)
        return
    # Entry priced at current observed pool quote, not the trader's old transaction price.
    # Total paid includes 1% fees/slippage; no direct execution is implemented.
    entry_cost = round(alloc*(1+COST_PER_SIDE), 6)
    if entry_cost > state['cash_gbp']: return
    pos = dict(wallet=wallet, token=token, pool_name=ev['pool_name'], opened_at=now_iso(),
               entry_price_usd=price, last_mark_price_usd=price, signal_at=ev['timestamp'].isoformat(),
               notional_gbp=alloc, cost_gbp=entry_cost, signal_id=ev['id'],
               mint=((state.get('research') or {}).get('decision_v1') or {}).get('pool_mints',{}).get(token),
               entry_assessment=assessment)
    state['cash_gbp'] = round(state['cash_gbp'] - entry_cost, 6)
    state['positions'].append(pos)
    if assessment and assessment['history']['shrunk_roi_pct'] > 0:
        log_decision(state, 'POSITIVE_SELECTION', wallet, token,
                     'positive shrunk token ROI prioritised; sizing still requires OOS validation',
                     history=assessment['history'])
    log_decision(state, 'PAPER_BUY', wallet, token, 'qualified copied signal at current pool quote',
                 notional_gbp=alloc, score=ws, feature_weight=feature_weight, feature_reason=feature_reason, signal_age_seconds=round((current-ev['timestamp']).total_seconds(),1))


def maintain_positions(state, prices, current):
    for pos in list(state['positions']):
        price = prices.get(pos['token'])
        if not price or price <= 0:
            log_decision(state, 'HOLD_NO_PRICE', pos['wallet'], pos['token'], 'no fresh pool price; never fabricate valuation')
            continue
        pos['last_mark_price_usd'] = price
        return_pct = 100*((price/pos['entry_price_usd'])*(1-COST_PER_SIDE)/(1+COST_PER_SIDE)-1)
        hours = (current-(parse_time(pos['opened_at']) or current)).total_seconds()/3600
        if return_pct <= -12: close_position(state, pos, price, '12% paper stop loss')
        elif return_pct >= 20: close_position(state, pos, price, '20% paper take profit')
        elif hours >= MAX_HOLD_HOURS: close_position(state, pos, price, '6-hour maximum hold')


def run_cycle(fetch=api, path=STATE, screen_token=None):
    if screen_token is None:
        from .safety import inspect_token as screen_token
    state = load(path)
    if fetch is api:
        from .primary_feed import PrimaryFeed
        global _PRIMARY_FEED
        _PRIMARY_FEED = PrimaryFeed(state.setdefault('research',{}).setdefault('primary_provider_v1',{}))
    whale_previous_run = state.get('last_run')
    current = dt.datetime.now(UTC)
    first = state['last_run'] is None
    errors = []
    screened_pools = 0
    sampled_feeds = 0
    skipped_risk = 0
    unavailable_risk = 0
    state["screening"] = []
    # A single provider failure must not invalidate unrelated safely screened
    # pools. Missing risk evidence always fails closed for its own token.
    # Store recent IDs to avoid acting on the same on-chain trade multiple times.
    seen = set(state['seen_trades'])
    pools = []
    try:
        payload = fetch('/networks/solana/trending_pools', {'page': 1, 'include':'base_token'})
        from .adaptive import enrich_meta
        pools = [enrich_meta(x, pool_meta(x)) for x in payload.get('data', [])]
        candidate_pools = [m for m in pools if eligible(m)][:4]
    except Exception as e:
        candidate_pools = []
        errors.append('pool discovery: '+str(e)[:240])
    prices = {}
    quote_times = {}
    discovery_at = dt.datetime.now(UTC)
    for m in candidate_pools:
        prices[m['pool']] = m['price_usd']
        quote_times[m['pool']] = discovery_at
    from .adaptive import ensure, shadow_tokens
    research=ensure(state)
    research['cycle_errors'] = []
    # Existing positions need fresh prices even when primary Gecko discovery
    # fails or enters its persistent 429 cooldown. Public DEX Screener returns
    # pair-specific quotes, NOT token-risk approval or attributable swaps.
    outstanding=list(dict.fromkeys(
        [p['token'] for p in state['positions'] if p['token'] not in prices]+
        [t for t in shadow_tokens(state) if t not in prices]))
    research['alternate_price_feed_v1']={'status':'NOT_REQUIRED' if not outstanding else 'NOT_USED',
                                          'quoted_pools':0, 'provider':'dexscreener'}
    if fetch is api and outstanding:
        try:
            from .market_resilience import fetch_pairs
            fallback=fetch_pairs(outstanding[:30])
            marked_at=dt.datetime.now(UTC)
            for pool,price in fallback.items():
                prices[pool]=price
                quote_times[pool]=marked_at
            research['alternate_price_feed_v1']={
                'status':'OK' if len(fallback)==len(outstanding) else 'PARTIAL',
                'quoted_pools':len(fallback), 'requested_pools':len(outstanding),
                'provider':'dexscreener'}
        except Exception as exc:
            research['alternate_price_feed_v1']={
                'status':'UNAVAILABLE','quoted_pools':0,'requested_pools':len(outstanding),
                'provider':'dexscreener', 'error':str(exc)[:130]}
    # Only if quote fallback failed: a bounded primary detail attempt may
    # still preserve a mark. Never replay a cached quote as a current price.
    for pos in state['positions']:
        if pos['token'] in prices:continue
        try:
            detail=fetch(f"/networks/solana/pools/{urllib.parse.quote(pos['token'], safe='')}",
                         {'include':'base_token'})
            m=pool_meta(detail.get('data') or {})
            if m['price_usd'] and m['price_usd']>0:
                prices[pos['token']]=m['price_usd']
                quote_times[pos['token']]=dt.datetime.now(UTC)
        except Exception as exc:
            errors.append('mark '+pos['token']+': '+str(exc)[:160])
    for research_token in shadow_tokens(state):
        if research_token in prices:continue
        try:
            from .adaptive import fast_shadow_pool
            detail=(fast_shadow_pool(research_token) if fetch is api else
                    fetch(f"/networks/solana/pools/{urllib.parse.quote(research_token, safe='')}",
                          {'include':'base_token'}))
            meta=pool_meta(detail.get('data') or {})
            if meta['price_usd'] and meta['price_usd']>0:
                prices[research_token]=meta['price_usd']
                quote_times[research_token]=dt.datetime.now(UTC)
            else:raise ValueError('Shadow pool has no valid current price')
        except Exception as exc:
            research['cycle_errors'].append('shadow mark '+str(research_token)[:48]+': '+str(exc)[:120])
    maintain_positions(state, prices, current)
    new_events = []
    # Rotate only the limited swap-feed reads. Risk screening still evaluates
    # all discovered candidates. Skipped pools are recorded, not falsely
    # labelled as sampled or treated as a market-data outage.
    production=(fetch is api)
    cursor=int(state.setdefault('research',{}).get('main_trade_cursor',0))
    if production and candidate_pools:
        offset=cursor%len(candidate_pools)
        ordered_pools=candidate_pools[offset:]+candidate_pools[:offset]
        state['research']['main_trade_cursor']=(
            cursor+MAX_MAIN_TRADE_FEEDS_PER_CYCLE)%len(candidate_pools)
    else:
        ordered_pools=candidate_pools
    budget_deferred=0
    for pool in ordered_pools:
        mint = pool.get('mint', '')
        try:
            assessment = screen_token(mint)
            # Backwards compatibility for injected Boolean test screeners.
            if isinstance(assessment, bool):
                assessment = {'allowed': assessment,
                              'status': 'PASS' if assessment else 'REJECTED',
                              'reason': 'legacy or mock screening verdict'}
            if not isinstance(assessment, dict):
                raise ValueError('security checker returned invalid result')
            status = assessment.get('status')
            if (status not in ('PASS', 'REJECTED', 'UNAVAILABLE') or
                    (status == 'PASS') != (assessment.get('allowed') is True)):
                raise ValueError('security checker returned contradictory status')
        except Exception:
            assessment = {'allowed': False, 'status': 'UNAVAILABLE',
                          'reason': 'security checker exception or malformed result'}
        verdict = {k: assessment.get(k) for k in
                   ('status', 'reason', 'score_normalised', 'http_status')}
        verdict['mint'] = mint
        state['screening'].append(verdict)
        if assessment['status'] != 'PASS':
            skipped_risk += 1
            log_decision(state, 'SKIP_TOKEN', token=pool['pool'],
                         reason='security '+assessment['status'].lower()+': '+str(assessment.get('reason','')))
            if assessment['status'] == 'UNAVAILABLE':
                unavailable_risk += 1
                errors.append('token security provider unavailable for '+str(mint)[:44]
                              +' ('+str(assessment.get('reason','unknown'))+')')
            continue
        screened_pools += 1
        if production and screened_pools>MAX_MAIN_TRADE_FEEDS_PER_CYCLE:
            budget_deferred+=1
            continue  # Not a provider failure; never generate unobserved trades.
        try:
            payload = fetch(f"/networks/solana/pools/{urllib.parse.quote(pool['pool'], safe='')}/trades", {'trade_volume_in_usd_greater_than': MIN_TRADE_USD})
            if not isinstance(payload.get('data'), list):
                raise ValueError('Malformed trade feed: data not a list')
            sampled_feeds += 1
            for raw in payload.get('data', []):
                ev = extract_event(raw, pool)
                if not ev:
                    state['unattributed_events'] = state.get('unattributed_events',0)+1
                    continue
                if ev['id'] in seen: continue
                seen.add(ev['id'])
                # Count all observed transactions as discovery evidence, but never open from pre-start history.
                observed = state['observed'].setdefault(ev['wallet'], {'count': 0, 'last_seen': None})
                observed['count'] += 1
                observed['last_seen'] = ev['timestamp'].isoformat()
                from .adaptive import observe_event
                observe_event(state, ev, current, pool)
                age = (current-ev['timestamp']).total_seconds()
                if (not first and 0 <= age <= MAX_TRADE_AGE_SECONDS
                        and ev['timestamp'] > (parse_time(state['last_run']) or current)):
                    new_events.append(ev)
                elif not first:
                    state['stale_signals'] = state.get('stale_signals',0)+1
        except Exception as e:
            errors.append('trades '+pool['pool']+': '+str(e)[:180])
    # On the first run, deliberately record trades for discovery only and never copy them.
    # No stale purchases from before the previous scan if a schedule is delayed.
    from .adaptive import research_cycle, conflicting_keys
    # News budget: two 4s requests at most once per 15 minutes; no market API calls.
    from .news import refresh
    from .decision import prepare, observe_forward
    if fetch is api:
        refresh(state, dt.datetime.now(UTC))
    current = dt.datetime.now(UTC)
    prepare(state, candidate_pools, current)
    fresh_prices = {token:price for token,price in prices.items()
                    if token in quote_times and 0 <= (current-quote_times[token]).total_seconds() <= MAX_TRADE_AGE_SECONDS}
    observe_forward(state, new_events, fresh_prices, current)
    research_cycle(state, candidate_pools, prices, new_events, current)
    sells_in_cycle = conflicting_keys(new_events)
    # Process sells before buys, then prioritise profitable token histories.
    # Same-token signals retain chronological order; no extra exposure is earned.
    from .decision import history
    for ev in sorted(new_events, key=lambda x: (x['kind'] != 'sell',
                     -history(state,x['token'],current)['shrunk_roi_pct'] if x['kind']=='buy' else 0,
                     x['timestamp'])):
        if ev['kind'] == 'buy' and (ev['wallet'], ev['token']) in sells_in_cycle:
            log_decision(state, 'SKIP', ev['wallet'], ev['token'],
                         'Conflicting buy/sell signals observed in one scan; avoid immediate churn')
            continue
        if ev['kind'] == 'sell':
            for pos in list(state['positions']):
                if pos['wallet'] == ev['wallet'] and pos['token'] == ev['token']:
                    close_position(state, pos, prices.get(ev['token']), 'observed trader sell')
        elif ev['kind'] == 'buy' and ev['token'] in prices:
            decision_now = dt.datetime.now(UTC)
            if not 0 <= (decision_now-quote_times[ev['token']]).total_seconds() <= MAX_TRADE_AGE_SECONDS:
                log_decision(state,'SKIP',ev['wallet'],ev['token'],'entry quote expired during data collection')
                continue
            if not 0 <= (decision_now-ev['timestamp']).total_seconds() <= MAX_TRADE_AGE_SECONDS:
                log_decision(state,'SKIP',ev['wallet'],ev['token'],'signal expired during data collection')
                continue
            maybe_open(state, ev, prices[ev['token']], decision_now, prices)
    # Keep recent event IDs in insertion order rather than lexicographic order.
    # The event-time gate also rejects observations older than the prior cycle.
    old_ids = state['seen_trades']
    state['seen_trades'] = (old_ids + [x for x in seen if x not in set(old_ids)])[-12000:]
    state['observed'] = dict(sorted(state['observed'].items(), key=lambda p: p[1].get('last_seen') or '', reverse=True)[:3000])
    state['watched_pools'] = candidate_pools
    state['last_run'] = now_iso()
    state['completed_cycles'] = state.get('completed_cycles',0)+1
    if sampled_feeds:
        state['last_data_at'] = now_iso()
    state['errors'] = (state['errors'] + [{'at': now_iso(), 'error': x} for x in errors])[-80:]
    # Isolate a PARTIAL security-provider outage only when at least one safe
    # token actually delivered an on-chain trade feed and ALL observed errors
    # came from unavailable security checks. Other failures remain degraded.
    partial_screening_only = bool(
        unavailable_risk and screened_pools and sampled_feeds and
        len(errors) == unavailable_risk and
        all(x.startswith('token security provider unavailable for ') for x in errors))
    partial_trade_feeds_only = bool(
        sampled_feeds and len(errors) > 0 and
        all(x.startswith('trades ') for x in errors))
    state['cycle_health'] = {
        'screened_pass': screened_pools,
        'screened_unavailable': unavailable_risk,
        'screened_rejected_or_unavailable': skipped_risk,
        'trade_feeds_sampled': sampled_feeds,
        'trade_feeds_budget_deferred': budget_deferred,
        'trade_feeds_attempted': screened_pools - budget_deferred,
        'alternate_quoted_pools': research['alternate_price_feed_v1'].get('quoted_pools',0),
        'trade_feeds_unavailable': sum(x.startswith('trades ') for x in errors),
        'candidate_pools': len(candidate_pools),
        'errors_this_cycle': len(errors),
        # Diagnosable in tiny docs/health.json; bounded, no wallet history.
        'error_messages': [str(message)[:200] for message in errors[-6:]],
        'partial_screening_only': partial_screening_only,
        'partial_trade_feeds_only': partial_trade_feeds_only,
        'rate_limit_errors': sum('429' in x for x in errors),
        'screening_http_statuses': [
            v.get('http_status') for v in state['screening']
            if v.get('status') == 'UNAVAILABLE' and v.get('http_status') is not None],
    }
    state['last_status'] = ('API_ERROR' if not candidate_pools and errors
                            else 'NO_ELIGIBLE_POOLS' if not candidate_pools
                            else 'SCREENING_UNAVAILABLE' if candidate_pools and unavailable_risk and not screened_pools
                            else 'NO_SAFE_POOLS' if candidate_pools and not screened_pools and not errors
                            else 'TRADE_FEEDS_FAILED' if screened_pools and not sampled_feeds
                            else 'PARTIAL_SCREENING_UNAVAILABLE' if partial_screening_only
                            else 'PARTIAL_TRADE_FEEDS_UNAVAILABLE' if partial_trade_feeds_only
                            else 'DEGRADED' if errors
                            else 'BOOTSTRAPPED_NO_TRADES' if first else 'OK')
    from .adaptive import finalize
    finalize(state, current)
    # V3 is observational: independent flow and shadow state only.
    # Never permit a new research-provider failure to block V2 or account persistence.
    try:
        from .whales import whale_cycle
        # A primary 429 applies to this provider, including supplemental Gecko reads.
        primary_health=(state.get('research') or {}).get('primary_provider_v1') or {}
        retry=parse_time(primary_health.get('retry_at'))
        if retry and retry>dt.datetime.now(UTC):
            health=state['research'].setdefault('whale_v3',{}).setdefault('provider_health',{})
            for group in ('gecko_quotes','gecko_trades'):
                existing=health.setdefault(group,{})
                prior=parse_time(existing.get('retry_at'))
                if not prior or prior<retry:
                    existing.update(retry_at=retry.isoformat(),http_status=429,last_error='Primary provider rate-limit backoff')
        # Supplemental GeckoTerminal reads cannot outrank the main account
        # when primary market discovery/trades are unavailable or cooling down.
        # Retain prior whale research and shadow positions; resume next cycle.
        provider_cooldown=parse_time(primary_health.get('retry_at'))
        last_429=parse_time(primary_health.get('last_rate_limit_at'))
        now_provider=dt.datetime.now(UTC)
        primary_busy=bool((provider_cooldown and provider_cooldown>now_provider) or
                          (last_429 and dt.timedelta(0)<=now_provider-last_429<dt.timedelta(minutes=30)))
        if fetch is api and (primary_busy or state['last_status'] in
                             ('API_ERROR','TRADE_FEEDS_FAILED','SCREENING_UNAVAILABLE')):
            whale_research=state['research'].setdefault('whale_v3',{})
            whale_research['status']='DEFERRED_PRIMARY_PRIORITY'
            whale_research['last_deferral_at']=current.isoformat()
            whale_research['last_deferral_reason']='Main free-provider access limited; preserve capacity and existing shadow history'
        else:
            whale_cycle(state, candidate_pools, new_events, dict(prices), current,
                        fetch=fetch, screener=screen_token, previous_run=whale_previous_run, discovered=pools)
    except Exception as v3_exc:
        from .whales import initialize, record_issue
        whale_research = initialize(state)
        record_issue(whale_research, 'V3 isolated research failure: '+str(v3_exc)[:145])
        whale_research['status'] = 'DEGRADED'
    # Independent, bounded public futures PAPER ledger; never changes GBP positions.
    if fetch is api:
        from .strategies import run as run_strategies
        run_strategies(state)
    # Credential is injected only via GitHub encrypted Actions secret.
    # This bounded RPC observation is NOT transaction parsing / entry approval.
    if fetch is api:
        from .helius_rpc import probe as probe_helius
        probe_helius(state,candidate_pools or state.get('watched_pools',[]),dt.datetime.now(UTC))
    from .evaluation import safe_update, observe_positions
    try:
        observe_positions(state,prices,current)
    except Exception as exc:
        state['research'].setdefault('evaluation_v1',{})['path_error']=str(exc)[:160]
    safe_update(state,current)
    state['snapshots'].append(dict(at=now_iso(), equity_gbp=equity(state, prices), cash_gbp=round(state['cash_gbp'], 2),
                                   open_positions=len(state['positions']), closed_trades=len(state['closed']),
                                   watched_pools=len(candidate_pools), sampled_feeds=sampled_feeds, screened_pools=screened_pools, status=state['last_status']))
    state['snapshots'] = state['snapshots'][-15000:]
    save(state, path)
    return state
