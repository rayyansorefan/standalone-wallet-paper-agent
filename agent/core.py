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
MAX_OPEN = 5
MAX_HOLD_HOURS = 6.0
MIN_WALLET_SEEN = 3
MIN_TRADE_USD = 100.0
UTC = dt.timezone.utc


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
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=18) as r:
                payload = json.load(r)
            if not isinstance(payload, dict) or 'errors' in payload:
                raise RuntimeError(f'API response error: {str(payload.get("errors"))[:300]}')
            return payload
        except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as exc:
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
    trades = [x for x in state['closed'] if x['wallet'] == wallet]
    n = len(trades)
    wins = sum(1 for x in trades if x['net_pnl_gbp'] > 0)
    net = sum(x['net_pnl_gbp'] for x in trades)
    mean = sum(x['roi_pct'] for x in trades) / n if n else 0.0
    # Shrink estimates toward zero; no illusion of certainty with small N.
    shrunk = mean * n / (n + 10)
    observed = state['observed'].get(wallet, {})
    return dict(closed=n, win_rate=round(100*wins/n, 2) if n else None,
                net_gbp=round(net, 2), shrunk_roi_pct=round(shrunk, 3), seen=observed.get('count', 0))


def wallet_risk_fraction(stats):
    if stats['closed'] >= 5 and stats['shrunk_roi_pct'] > 0 and (stats['win_rate'] or 0) >= 50:
        return 0.015
    if stats['closed'] >= 3 and stats['shrunk_roi_pct'] < -1:
        return 0.0
    return 0.005  # maximum £10 exploration at starting equity


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
    ws = wallet_stats(state, wallet)
    if ws['seen'] < MIN_WALLET_SEEN: reason = 'wallet has fewer than 3 observed qualifying trades'
    elif len(state['positions']) >= MAX_OPEN: reason = 'portfolio position limit'
    elif any(x['wallet'] == wallet for x in state['positions']): reason = 'one position per wallet'
    elif any(x['token'] == token for x in state['positions']): reason = 'one position per pool'
    elif any(x['wallet'] == wallet and x['token'] == token and
             (current-(parse_time(x['exit_at']) or current)).total_seconds() < 1800 for x in state['closed'][-50:]):
        reason = '30-minute cooldown'
    alloc_fraction = wallet_risk_fraction(ws)
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
               notional_gbp=alloc, cost_gbp=entry_cost, signal_id=ev['id'])
    state['cash_gbp'] = round(state['cash_gbp'] - entry_cost, 6)
    state['positions'].append(pos)
    log_decision(state, 'PAPER_BUY', wallet, token, 'qualified copied signal at current pool quote',
                 notional_gbp=alloc, score=ws, signal_age_seconds=round((current-ev['timestamp']).total_seconds(),1))


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
        from .safety import screen_token as screen_token
    state = load(path)
    current = dt.datetime.now(UTC)
    first = state['last_run'] is None
    errors = []
    screened_pools = 0
    sampled_feeds = 0
    skipped_risk = 0
    # Store recent IDs to avoid acting on the same on-chain trade multiple times.
    seen = set(state['seen_trades'])
    try:
        payload = fetch('/networks/solana/trending_pools', {'page': 1, 'include':'base_token'})
        pools = [pool_meta(x) for x in payload.get('data', [])]
        candidate_pools = [m for m in pools if eligible(m)][:4]
    except Exception as e:
        candidate_pools = []
        errors.append('pool discovery: '+str(e)[:240])
    prices = {}
    for m in candidate_pools:
        prices[m['pool']] = m['price_usd']
    # Always refresh the pools held in the portfolio even if no longer trending.
    for pos in state['positions']:
        if pos['token'] in prices: continue
        try:
            detail = fetch(f"/networks/solana/pools/{urllib.parse.quote(pos['token'], safe='')}", {'include':'base_token'})
            m = pool_meta(detail.get('data') or {})
            if m['price_usd'] and m['price_usd'] > 0: prices[pos['token']] = m['price_usd']
        except Exception as e: errors.append('mark '+pos['token']+': '+str(e)[:160])
    maintain_positions(state, prices, current)
    new_events = []
    for pool in candidate_pools:
        if not screen_token(pool.get('mint', '')):
            skipped_risk += 1
            errors.append('token safety unavailable or failed: '+str(pool.get('mint',''))[:44])
            continue
        screened_pools += 1
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
    for ev in sorted(new_events, key=lambda x: x['timestamp']):
        if ev['kind'] == 'sell':
            for pos in list(state['positions']):
                if pos['wallet'] == ev['wallet'] and pos['token'] == ev['token']:
                    close_position(state, pos, prices.get(ev['token']), 'observed trader sell')
        elif ev['kind'] == 'buy' and ev['token'] in prices:
            maybe_open(state, ev, prices[ev['token']], current, prices)
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
    state['last_status'] = ('API_ERROR' if not candidate_pools and errors
                            else 'NO_ELIGIBLE_POOLS' if not candidate_pools
                            else 'SCREENING_UNAVAILABLE' if candidate_pools and not screened_pools
                            else 'TRADE_FEEDS_FAILED' if not sampled_feeds
                            else 'DEGRADED' if errors
                            else 'BOOTSTRAPPED_NO_TRADES' if first else 'OK')
    state['snapshots'].append(dict(at=now_iso(), equity_gbp=equity(state, prices), cash_gbp=round(state['cash_gbp'], 2),
                                   open_positions=len(state['positions']), closed_trades=len(state['closed']),
                                   watched_pools=len(candidate_pools), sampled_feeds=sampled_feeds, screened_pools=screened_pools, status=state['last_status']))
    state['snapshots'] = state['snapshots'][-15000:]
    save(state, path)
    return state
