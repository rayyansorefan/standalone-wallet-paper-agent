"""Evidence-gated position management for the ORIGINAL GBP PAPER ledger.

Each decision uses current, observed pool prices; stops are simulated at the
next observation and can gap. No live trading, doubling down or synthetic
quotes. The total entry notional is capped at 1% of paper equity for an
unvalidated sender, and 1.5% for an independently reinforced sender.
"""
import datetime as dt
import math

ADD_THRESHOLD_NET_ROI_PCT = 10.
MAX_ADD_FRACTION = .005
EXPLORATION_TOTAL_CAP = .010
REINFORCED_TOTAL_CAP = .015
MIN_HOLD_SECONDS = 600
MIN_SAMPLE_SECONDS = 240
TRAIL_PCT = .07
LOCK_PROFIT_PCT = .02
MAX_ADDITIONS = 1
MAX_MARKS = 3


def finite(x):
    try:
        f=float(x)
        return f if math.isfinite(f) else None
    except (ValueError,TypeError,OverflowError):
        return None


def stamp(value):
    try:
        v=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return v.astimezone(dt.timezone.utc) if v.tzinfo else None
    except (ValueError,TypeError,OverflowError):
        return None


def net_roi(pos,price,cost_per_side=.01):
    entry=finite(pos.get('entry_price_usd'))
    notional=finite(pos.get('notional_gbp'))
    paid=finite(pos.get('cost_gbp'))
    px=finite(price)
    if any(x is None or x<=0 for x in (entry,notional,paid,px)):
        return None
    return 100*((notional*px/entry*(1-cost_per_side)-paid)/paid)


def confirmed_rising(pos,current):
    marks=pos.get('recent_marks') or []
    if len(marks)<3:return False
    seq=marks[-3:]
    times=[stamp(x.get('at')) for x in seq]
    prices=[finite(x.get('price_usd')) for x in seq]
    return (all(t is not None for t in times)
            and all(p is not None and p>0 for p in prices)
            and 0 <= (current-times[-1]).total_seconds() < 1.5
            and MIN_SAMPLE_SECONDS <= (times[1]-times[0]).total_seconds() <= 900
            and MIN_SAMPLE_SECONDS <= (times[2]-times[1]).total_seconds() <= 900
            and prices[0]<prices[1]<prices[2])


def observe(pos,price,current,cost_per_side=.01):
    """Update monitoring evidence; must only be called for a FRESH valid quote."""
    px=finite(price)
    if px is None or px<=0 or current.tzinfo is None:
        return None
    iso=current.isoformat(timespec='seconds')
    marks=pos.setdefault('recent_marks',[])
    if marks and marks[-1].get('at')==iso:
        marks[-1]={'at':iso,'price_usd':px}
    else:
        marks.append({'at':iso,'price_usd':px})
    pos['recent_marks']=marks[-MAX_MARKS:]
    pos['last_mark_price_usd']=px
    pos['last_mark_at']=iso
    pos['peak_mark_price_usd']=max(px,finite(pos.get('peak_mark_price_usd')) or 0)
    gain=net_roi(pos,px,cost_per_side)
    if gain is None:return None
    pos['highest_net_roi_pct']=round(max(gain,finite(pos.get('highest_net_roi_pct')) or gain),3)
    strong=confirmed_rising(pos,current)
    # Tighten only after consecutive CURRENT observations; never loosen an
    # existing stop. Keep the original 12% downside and 6h expiry otherwise.
    if gain>=ADD_THRESHOLD_NET_ROI_PCT and strong:
        entry=finite(pos['entry_price_usd'])
        cost=finite(pos['cost_gbp'])
        notional=finite(pos['notional_gbp'])
        breakeven=(entry*cost)/(notional*(1-cost_per_side))
        protective=max(pos['peak_mark_price_usd']*(1-TRAIL_PCT),
                       breakeven*(1+LOCK_PROFIT_PCT))
        old=finite(pos.get('trailing_stop_price_usd')) or 0
        if protective < px:
            pos['trailing_stop_price_usd']=round(max(old,protective),12)
    pos['position_action']='HOLD_PROTECTED' if pos.get('trailing_stop_price_usd') else (
        'WATCHING_WINNER' if gain>0 else 'WATCHING_LOSS')
    pos['last_net_roi_pct']=round(gain,3)
    return gain


def addition_amount(state,pos,price,current,*,safe_pools,conflicting_sells,
                    fresh_quote_at,wallet_profile,equity_gbp,cost_per_side=.01):
    """Return (extra GBP, reason), before any paper ledger mutation."""
    px=finite(price)
    if px is None or px<=0 or current.tzinfo is None:
        return 0.,'unavailable quote'
    if pos.get('token') not in safe_pools:
        return 0.,'no current approved token security screen'
    if (pos.get('wallet'),pos.get('token')) in conflicting_sells:
        return 0.,'observed sender sell'
    seen=stamp(fresh_quote_at)
    if not seen or not 0<=(current-seen).total_seconds()<=240:
        return 0.,'not a fresh quote'
    age=stamp(pos.get('opened_at'))
    if not age or (current-age).total_seconds()<MIN_HOLD_SECONDS:
        return 0.,'insufficient holding history'
    if len(pos.get('additions') or [])>=MAX_ADDITIONS:
        return 0.,'one addition per position maximum'
    if not confirmed_rising(pos,stamp(pos.get('last_mark_at')) or current):
        return 0.,'no consecutive rising price evidence'
    gain=net_roi(pos,px,cost_per_side)
    if gain is None or gain<ADD_THRESHOLD_NET_ROI_PCT or gain>=35:
        return 0.,'outside gated profitable continuation window'
    if wallet_profile.get('reinforcement_tier')=='suspended' or float(wallet_profile.get('risk_fraction',0))<=0:
        return 0.,'loss suspension / sender not eligible'
    cap=(REINFORCED_TOTAL_CAP if
         str(wallet_profile.get('reinforcement_tier','')).startswith('reinforced')
         else EXPLORATION_TOTAL_CAP)
    # Equity is calculated from fresh full-account quotes by the caller.
    # Never infer total exposure from stale individual marks.
    equity=finite(equity_gbp)
    if equity is None or equity<=0:
        return 0.,'missing complete live paper equity'
    used=finite(pos.get('notional_gbp')) or 0
    cash=finite(state.get('cash_gbp')) or 0
    room=min(equity*MAX_ADD_FRACTION,cap*equity-used,cash*.98/(1+cost_per_side))
    amount=round(max(0,room),2)
    if amount<3:
        return 0.,'portfolio/sender cap or cash restriction'
    return amount,'sustained net winner and current security confirmation'


def apply_add(state,pos,price,extra,current,cost_per_side=.01):
    """One atomic, modelled paper add; preserve weighted acquisition cost."""
    old_n=float(pos['notional_gbp'])
    old_e=float(pos['entry_price_usd'])
    old_cost=float(pos['cost_gbp'])
    if not (old_n>0 and old_e>0 and extra>0 and price>0):
        raise ValueError('Invalid simulated addition')
    fee=extra*cost_per_side
    if extra+fee>float(state['cash_gbp'])+1e-8:
        raise ValueError('Insufficient GBP paper cash')
    new_n=old_n+extra
    units=old_n/old_e+extra/price
    new_e=new_n/units
    pos['notional_gbp']=round(new_n,6)
    pos['entry_price_usd']=new_e
    pos['cost_gbp']=round(old_cost+extra+fee,6)
    pos['additions']=(pos.get('additions') or [])+[{
        'at':current.isoformat(timespec='seconds'),'notional_gbp':extra,
        'price_usd':price,'modelled_entry_fee_gbp':round(fee,6)}]
    pos['position_action']='ADDED_TO_WINNER'
    pos['last_net_roi_pct']=round(net_roi(pos,price,cost_per_side),3)
    state['cash_gbp']=round(float(state['cash_gbp'])-extra-fee,6)
    # Adjust profit-protective stop to the newly blended acquisition cost
    # without moving a previous stop DOWN, or setting it above the current mark.
    break_even=new_e*pos['cost_gbp']/(new_n*(1-cost_per_side))
    existing=finite(pos.get('trailing_stop_price_usd')) or 0
    candidate=max(existing,break_even*(1+LOCK_PROFIT_PCT))
    if candidate<price:
        pos['trailing_stop_price_usd']=round(candidate,12)
    return pos
