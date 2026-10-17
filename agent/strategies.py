"""Free, deterministic, forward-only futures PAPER challenger.

One independent USD ledger; never writes the original GBP account. Public GETs
only, no credentials, orders, AI calls or automatic promotion. Versioned rules
are registered before the first entry. Five-minute sampled exits can gap.
"""
import datetime as dt
import json
import math
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from .strategy_lab import (market_regime, context_adjustment, observe_forward,
                           improved_stop, has_cost_room, priority_score,
                           recovery_state)

UTC = dt.timezone.utc
BASE = 'https://futures.kraken.com'
VERSION = 'momentum-fade-2'
FEE = .0005
SLIP = .001
COST = FEE + SLIP


def number(x):
    try:
        n = float(x)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def stamp(s):
    try:
        t = dt.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
        return t if t.tzinfo else None
    except ValueError:
        return None


def get(path):
    req = urllib.request.Request(BASE + path, headers={'User-Agent':'PaperResearch/1.0', 'Cache-Control':'no-cache'})
    with urllib.request.urlopen(req, timeout=5) as r:
        raw = r.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('Market response exceeds budget')
    return json.loads(raw)


def initialize(state, now):
    return state.setdefault('research', {}).setdefault('strategies_v1', {
        'version':VERSION, 'registered_at':now.isoformat(), 'cash_usd':2000.,
        'starting_usd':2000., 'position':None, 'closed':[], 'events':[],
        'status':'UNPROVEN', 'equity_usd':2000., 'peak_equity_usd':2000.,
        'max_drawdown_pct':0., 'cycles':0,
        'rules':{'paper_only':True, 'max_positions':1, 'risk_fraction':.0025,
                 'entry_notional_cap':.25, 'total_notional_cap':.375,
                 'fee_each_side':FEE, 'slippage_each_side':SLIP,
                 'carry':'Adverse reserve: max(0.01%/hour, absolute observed relative funding/hour); no funding credits; estimate, not exchange settlement',
                 'exits':'Observed quotes every five minutes; no intrabar fills or guaranteed stop price',
                 'news':'Broad crypto risk veto; no inferred coin-specific sentiment',
                 'promotion':'Never automatically replaces the original account'}})


def event(book, now, action, **data):
    book['events'] = (book['events'] + [dict(at=now.isoformat(), action=action, **data)])[-120:]


def market(book, now, fetch=get):
    payload = fetch('/derivatives/api/v3/tickers')
    at = stamp(payload.get('serverTime'))
    if payload.get('result') != 'success' or not at or not -15 <= (now-at).total_seconds() <= 90:
        raise ValueError('Missing or stale ticker server time')
    quotes = {}
    for t in payload.get('tickers', []):
        symbol = t.get('symbol', '')
        bid, ask = number(t.get('bid')), number(t.get('ask'))
        if (not symbol.startswith('PF_') or not symbol.endswith('USD') or
                t.get('tag') != 'perpetual' or t.get('suspended') or t.get('postOnly') or
                bid is None or ask is None or not 0 < bid <= ask):
            continue
        t = dict(t, bid=bid, ask=ask, mid=(bid+ask)/2)
        quotes[symbol] = t
    eligible = [t for t in quotes.values() if
                (number(t.get('volumeQuote')) or 0) >= 1_000_000 and
                (t['ask']-t['bid'])/t['mid'] <= .002 and
                number(t.get('relativeFundingRate')) is not None]
    eligible.sort(key=lambda t:abs(number(t.get('change24h')) or 0), reverse=True)
    held = book.get('position')
    symbols = ([held['symbol']] if held else [])
    symbols += [t['symbol'] for t in eligible if t['symbol'] not in symbols][:6-len(symbols)]
    start, end = int(now.timestamp())-33000, int(now.timestamp())
    def candles(symbol):
        try:
            data = fetch(f'/api/charts/v1/trade/{symbol}/5m?from={start}&to={end}')
            return symbol, features(data.get('candles', []), now), None
        except Exception as exc:
            return symbol, None, str(exc)[:100]
    with ThreadPoolExecutor(max_workers=6) as executor:
        rows = list(executor.map(candles, symbols))
    book['feed'] = dict(at=at.isoformat(), eligible=len(eligible), scanned=len(symbols),
                        requests=1+len(symbols), errors={s:e for s,_,e in rows if e},
                        provider='Kraken public futures', max_requests=7)
    return quotes, {s:f for s,f,_ in rows if f}, {t['symbol'] for t in eligible}


def ema(values, span):
    result = values[0]
    for x in values[1:]:
        result += 2/(span+1)*(x-result)
    return result


def features(raw, now):
    bars = []
    for b in raw:
        vals = [number(b.get(k)) for k in ('time','open','high','low','close','volume')]
        if any(v is None for v in vals):
            raise ValueError('Invalid candle')
        t,o,h,l,c,v = vals
        if min(o,h,l,c) <= 0 or v < 0 or not l <= min(o,c) <= max(o,c) <= h:
            raise ValueError('Invalid OHLC')
        if t/1000 + 300 <= now.timestamp():
            bars.append((t/1000,o,h,l,c,v))
    bars.sort()
    if len(bars) < 60 or not 0 <= now.timestamp()-(bars[-1][0]+300) <= 600:
        raise ValueError('Insufficient or stale completed candles')
    bars = bars[-100:]
    if any(bars[i][0]-bars[i-1][0] != 300 for i in range(1,len(bars))):
        raise ValueError('Candle gap or duplicate')
    closes = [b[4] for b in bars]
    atr = sum(max(bars[i][2]-bars[i][3],abs(bars[i][2]-bars[i-1][4]),
                  abs(bars[i][3]-bars[i-1][4])) for i in range(len(bars)-14,len(bars)))/14
    if atr <= 0:
        raise ValueError('Zero ATR')
    recent = bars[-24:]
    peak_i = max(range(len(recent)), key=lambda i:recent[i][2])
    peak = recent[peak_i][2]
    peak_vol = sum(b[5] for b in recent[max(0,peak_i-2):peak_i+1]) / min(3,peak_i+1)
    vol = sum(b[5] for b in bars[-3:])/3
    baseline = sum(b[5] for b in bars[-23:-3])/20
    return dict(at=dt.datetime.fromtimestamp(bars[-1][0]+300,UTC).isoformat(),
                close=closes[-1], previous=closes[-2], atr=atr,
                ema_fast=ema(closes,6), ema_slow=ema(closes,20),
                r1h=closes[-1]/closes[-13]-1, r15m=closes[-1]/closes[-4]-1,
                volume_ratio=vol/baseline if baseline else 0,
                fade_volume_ratio=vol/peak_vol if peak_vol else 1,
                pump=peak/recent[0][1]-1, drawdown=(peak-closes[-1])/atr,
                peak_age=len(recent)-1-peak_i,
                lower_closes=closes[-1]<closes[-2]<closes[-3])


def setups(f):
    result = []
    direction = 1 if f['ema_fast'] > f['ema_slow'] else -1
    if (direction*f['r1h'] >= .006 and direction*f['r15m'] >= .001 and
            f['volume_ratio'] >= 1.3 and abs(f['close']-f['ema_slow']) <= 4*f['atr']):
        result.append(('momentum_long' if direction==1 else 'momentum_short',direction,
                       abs(f['r1h'])/max(f['atr']/f['close'],.0001)))
    if (f['pump'] >= .03 and f['peak_age'] >= 2 and f['drawdown'] >= 1 and
            f['fade_volume_ratio'] <= .65 and f['lower_closes'] and f['r15m'] < 0):
        result.append(('pump_fade',-1,f['drawdown']+f['pump']*100))
    return result


def feedback(book, setup, symbol, now):
    rows = [t for t in book['closed'] if t['setup']==setup and t.get('version',VERSION)==VERSION and stamp(t['exit_at']) <= now]
    # An asset's loss cooldown survives a change of strategy label.
    same = [t for t in book['closed'] if t['symbol']==symbol and stamp(t['exit_at']) <= now]
    cooldown = any(0 <= (now-stamp(t['exit_at'])).total_seconds() <
                   (7200 if t['net_usd']<0 else 1800) for t in same)
    recent = [t for t in rows if 0 <= (now-stamp(t['exit_at'])).total_seconds() < 86400]
    recovery = recovery_state(book,setup,now,rows)
    paused = recovery['status'] in ('PAUSED','RETESTING')
    # Fixed training/validation split per predeclared setup, no retrospective cohort search.
    train, valid = rows[:20], rows[20:]
    def robust(xs):
        profits = [t['net_usd'] for t in xs]
        return (sum(profits)-max([0]+profits)>0 and sum(t['stress_net_usd'] for t in xs)>0)
    reinforced = (len(valid)>=10 and len({t['symbol'] for t in rows})>=3 and
                  (now-stamp(book.get('policy_registered_at') or book['registered_at'])).total_seconds()>=14*86400 and
                  robust(train) and robust(valid))
    edge = sum(t['net_usd']/t['risk_usd'] for t in rows)/(len(rows)+10)
    return dict(allowed=not cooldown and recovery['allowed'], paused=paused,
                cooldown=cooldown, recovery=recovery, closed=len(rows),
                edge=edge, reinforced=reinforced,
                risk_multiplier=1.25 if reinforced else 1.)


def exit_value(p, q):
    px = q['bid']*(1-SLIP) if p['direction']==1 else q['ask']*(1+SLIP)
    gross = p['direction']*(px-p['entry'])*p['units']
    fee = p['units']*px*FEE
    return px,gross-fee-p['entry_fees']-p['carry_usd']


def news_allowed(state, now):
    news = state.get('research',{}).get('news_v1',{})
    checked = stamp(news.get('checked_at'))
    return bool(checked and 0 <= (now-checked).total_seconds()<=1800 and
                news.get('sources',{}).get('coindesk',{}).get('status')=='OK' and
                not news.get('risk_off'))


def advance(state, now, quotes, indicators, eligible):
    b = initialize(state,now)
    # Do not allow historic strategy evidence to certify the new policy.
    # Original and challenger balances, trade records and open positions survive.
    if b.get('version') != VERSION:
        previous = b.get('version')
        b['version'] = VERSION
        b['policy_registered_at'] = now.isoformat()
        event(b,now,'POLICY_VERSION_CHANGED',previous=previous,current=VERSION)
    p = b.get('position')
    closed_symbol = None
    if p:
        q = quotes.get(p['symbol'])
        f = indicators.get(p['symbol'])
        if q:
            hours = max(0,(now-stamp(p['carry_at'])).total_seconds()/3600)
            rate = max(.0001,abs(number(q.get('relativeFundingRate')) or .0001),p['carry_rate'])
            charge = p['units']*max(p['entry'],q['mid'])*rate*hours
            p['carry_usd'] += charge; b['cash_usd'] -= charge
            p.update(carry_at=now.isoformat(), carry_rate=rate)
            px, net = exit_value(p,q)
            p.update(mark=q['mid'], marked_at=now.isoformat(), net_usd=net)
            p['best'] = max(p['best'],q['mid']) if p['direction']==1 else min(p['best'],q['mid'])
            crossed = p['direction']*(q['mid']-p['stop']) <= 0
            age = (now-stamp(p['opened_at'])).total_seconds()
            reversal = f and p['setup']!='pump_fade' and (p['direction']*(f['ema_fast']-f['ema_slow'])<=0 or
                             (p['direction']*f['r15m']<=0 and f['volume_ratio']<.7))
            fade_ends = f and p['setup']=='pump_fade' and (f['r15m']>0 or
                        (f['volume_ratio']>1.3 and f['close']>f['previous']))
            reason = 'stop/trailing stop' if crossed else 'time limit' if age>=43200 else 'momentum/fade ended' if age>=900 and (reversal or fade_ends) else None
            if reason:
                gross = p['direction']*(px-p['entry'])*p['units']
                b['cash_usd'] += gross-p['units']*px*FEE
                record = dict(p, exit_at=now.isoformat(),exit_price=px,reason=reason,net_usd=net,
                              stress_net_usd=net-.0035*(p['entry_notional']+p['units']*px))
                b['closed'] = (b['closed']+[record])[-1000:]
                event(b,now,'CLOSE',symbol=p['symbol'],setup=p['setup'],net_usd=net,reason=reason)
                closed_symbol=p['symbol']; b['position']=None; p=None
            else:
                # Break-even at +0.5R; after +1R retain a portion of net profit.
                # Stops execute against subsequent observations, not guaranteed fills.
                atr = f['atr'] if f else (p.get('features') or {}).get('atr')
                revised_stop = improved_stop(p,q,net,atr)
                if revised_stop is not None:
                    p['stop'] = revised_stop
                    event(b,now,'PROFIT_STOP_RATCHET',symbol=p['symbol'],stop=revised_stop)
                if f and net>=p['risk_usd']:
                    still_valid=any(s==p['setup'] for s,_,_ in setups(f))
                    if not p['added'] and still_valid and news_allowed(state,now):
                        eq=b['cash_usd']+p['direction']*(q['mid']-p['entry'])*p['units']
                        add_notional=min(eq*.125,max(0,eq*.375-p['units']*q['mid']))
                        entry=q['ask']*(1+SLIP) if p['direction']==1 else q['bid']*(1-SLIP)
                        units=add_notional/entry
                        new_units=p['units']+units
                        new_entry=(p['entry']*p['units']+entry*units)/new_units
                        # Lock enough at the stop to cover all entry/exit costs and carry.
                        fees=p['entry_fees']+add_notional*FEE
                        lock=(new_entry+(fees+p['carry_usd'])/new_units)/(1-COST) if p['direction']==1 else (new_entry-(fees+p['carry_usd'])/new_units)/(1+COST)
                        stop=max(p['stop'],lock) if p['direction']==1 else min(p['stop'],lock)
                        if add_notional>0 and p['direction']*(q['mid']-stop)>0:
                            p.update(units=new_units,entry=new_entry,entry_fees=fees,stop=stop,
                                     entry_notional=p['entry_notional']+add_notional,added=True)
                            b['cash_usd']-=add_notional*FEE
                            p['net_usd']=exit_value(p,q)[1]
                            event(b,now,'ADD_WINNER',symbol=p['symbol'],notional_usd=add_notional)
        else:
            event(b,now,'HOLD_UNPRICED',symbol=p['symbol'],reason='No executable fresh quote; no fabricated exit')
    candidates=[]
    watched_setups=[]
    b['cost_hurdle_rejections'] = 0
    for symbol,f in indicators.items():
        if symbol not in eligible or symbol==closed_symbol:
            continue
        q=quotes.get(symbol)
        if not q:
            continue
        cost_ok=has_cost_room(f,q)
        setups_now=setups(f)
        if not cost_ok:
            b['cost_hurdle_rejections'] += 1
        for setup,direction,base_score in setups_now:
            memory=feedback(b,setup,symbol,now)
            regime=market_regime(f)
            learned=context_adjustment(b,setup,regime)
            memory={**memory,'learned':learned,
                    'allowed':memory['allowed'] and learned['status']!='NEGATIVE_FORWARD'}
            rank=priority_score(base_score,f,q,learned,memory['edge'])
            candidate=dict(symbol=symbol,setup=setup,direction=direction,
                           regime=regime,learning=learned,score=rank,
                           cost_qualified=cost_ok,feedback=memory,features=f)
            watched_setups.append(candidate)
            if cost_ok and rank>-999:
                candidates.append(candidate)
    candidates.sort(key=lambda c:c['score'],reverse=True)
    watched_setups.sort(key=lambda c:c['score'],reverse=True)
    b['candidates']=candidates[:12]
    b['ranking_policy']='V4_1_COST_NORMALIZED_WITH_FORWARD_FEEDBACK'
    b['news_allows_entry']=news_allowed(state,now)
    day=now.date().isoformat()
    current_equity=b['cash_usd']+(p['net_usd']+p['entry_fees']+p['carry_usd'] if p else 0)
    if b.get('day')!=day:
        b.update(day=day,day_start_equity=current_equity,entries_today=0)
    day_loss=current_equity-b['day_start_equity']
    selected_new = None
    if not p and news_allowed(state,now) and b['entries_today']<6 and day_loss > -b['starting_usd']*.02:
        for c in candidates:
            if not c['feedback']['allowed']:
                continue
            q=quotes[c['symbol']]; f=c['features']; direction=c['direction']
            risk=b['cash_usd']*.0025*c['feedback']['risk_multiplier']
            entry=q['ask']*(1+SLIP) if direction==1 else q['bid']*(1-SLIP)
            distance=max(2*f['atr'],entry*.005)
            notional=min(b['cash_usd']*.25,risk/(distance/entry+2*COST))
            fee=notional*FEE
            p=dict(symbol=c['symbol'],setup=c['setup'],direction=direction,
                   entry=entry,units=notional/entry,entry_notional=notional,entry_fees=fee,
                   opened_at=now.isoformat(),stop=entry-direction*distance,best=q['mid'],
                   mark=q['mid'],marked_at=now.isoformat(),added=False,risk_usd=risk,
                   carry_usd=0.,carry_at=now.isoformat(),
                   carry_rate=max(.0001,abs(number(q.get('relativeFundingRate')) or 0)),
                   features=f,feedback=c['feedback'],version=VERSION)
            p['net_usd']=exit_value(p,q)[1]
            b['position']=p; b['cash_usd']-=fee; b['entries_today']+=1
            selected_new=(symbol,c['setup'])
            event(b,now,'OPEN',symbol=p['symbol'],setup=p['setup'],direction=direction,notional_usd=notional)
            break
    # Record blocked setups too: their future outcomes identify whether the veto
    # avoided a loss or missed a positive forward quote. Never backfill.
    for c in watched_setups:
        if selected_new == (c['symbol'],c['setup']):
            reason=None
        elif not c['cost_qualified']:
            reason='COST_HURDLE'
        elif c['feedback']['recovery']['status'] in ('PAUSED','RETESTING'):
            reason='LOSS_SUSPENSION'
        elif c['learning']['status']=='NEGATIVE_FORWARD':
            reason='NEGATIVE_FORWARD'
        elif c['feedback']['cooldown']:
            reason='TOKEN_COOLDOWN'
        elif not b['news_allows_entry']:
            reason='NEWS_VETO'
        elif p:
            reason='POSITION_OCCUPIED'
        elif b['entries_today']>=6 or day_loss<=-b['starting_usd']*.02:
            reason='DAILY_LIMIT'
        else:
            reason='RANKED_BELOW_SELECTED'
        c['rejection_reason']=reason
    # Mark forward outcomes using current quotes before registering fresh signals.
    observe_forward(b,now,quotes,watched_setups,selected_new)
    p=b.get('position')
    # Cash includes fees and carry already; net includes them for the trade report only.
    unrealized=0.
    if p:
        unrealized=p['net_usd']+p['entry_fees']+p['carry_usd']
    b['equity_usd']=b['cash_usd']+unrealized
    b['peak_equity_usd']=max(b['peak_equity_usd'],b['equity_usd'])
    b['max_drawdown_pct']=max(b['max_drawdown_pct'],100*(1-b['equity_usd']/b['peak_equity_usd']))
    rows=b['closed']; wins=sum(t['net_usd']>0 for t in rows)
    gains=sum(max(0,t['net_usd']) for t in rows); losses=-sum(min(0,t['net_usd']) for t in rows)
    b['summary']=dict(closed=len(rows),wins=wins,net_usd=sum(t['net_usd'] for t in rows),
                      profit_factor=gains/losses if losses else None,
                      stress_net_usd=sum(t['stress_net_usd'] for t in rows),
                      feedback={s:feedback(b,s,'',now) for s in ('momentum_long','momentum_short','pump_fade')})
    b['last_run']=now.isoformat();b['cycles']+=1
    b['status']=('HOLD_UNPRICED' if p and p['symbol'] not in quotes else
                 'NO_FRESH_CANDLES' if not indicators else
                 'PARTIAL_MARKET_DATA' if b.get('feed',{}).get('errors') else
                 'COLLECTING_FORWARD_EVIDENCE')
    b['entry_status']='HOLDING' if p else 'NEWS_VETO' if not news_allowed(state,now) else 'DAILY_CAP' if b['entries_today']>=6 or day_loss<=-b['starting_usd']*.02 else 'NO_QUALIFIED_SETUP'
    return b


def run(state, now=None, fetch=get):
    live_clock=now is None
    now=now or dt.datetime.now(UTC)
    b=initialize(state,now)
    try:
        quotes, indicators, eligible=market(b,now,fetch)
        b.pop('error',None)
        return advance(state,dt.datetime.now(UTC) if live_clock else now,quotes,indicators,eligible)
    except Exception as exc:
        b.update(status='DATA_UNAVAILABLE',last_run=now.isoformat(),error=str(exc)[:160])
        return b
