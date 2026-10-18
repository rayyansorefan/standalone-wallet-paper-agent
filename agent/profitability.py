"""Read-only decomposition of recorded GBP closes; no inferred trading edge."""
import math
from .policy_evidence import certifiable_trade


def finite(v):
    if isinstance(v,bool):return None
    try:
        n=float(v)
        return n if math.isfinite(n) else None
    except (ValueError,TypeError,OverflowError):return None


def decompose(t):
    values=[finite(t.get(k)) for k in ('notional_gbp','entry_price_usd',
            'exit_price_usd','cost_gbp','proceeds_gbp','net_pnl_gbp')]
    if any(v is None for v in values):return None
    notional,entry,exit_price,cost,proceeds,net=values
    if min(notional,entry,exit_price,cost)<=0 or proceeds<0:return None
    # Each persisted money field is rounded to 4 decimals. A larger mismatch
    # is unknown/inconsistent evidence, never an invented fee or zero loss.
    if abs(proceeds-cost-net)>.001:return None
    gross_end=notional*exit_price/entry
    drag=(cost-notional)+(gross_end-proceeds)
    if drag < -.001:return None
    return dict(gross=gross_end-notional,drag=drag,net=net,
                cost_flipped=gross_end>notional and net<=0)


def exit_group(t):
    reason=str(t.get('exit_reason',''))
    for prefix,label in (
        ('4.5% observed net paper stop loss','observed_net_stop_4_5'),
        ('12%','legacy_stop_12'),('20% paper take profit','legacy_take_profit_20'),
        ('confirmed winner trailing stop','winner_trailing_stop'),
        ('observed trader sell','observed_trader_sell'),
        ('6-hour maximum hold','maximum_hold_6h')):
        if reason.startswith(prefix):return label
    return 'other_or_unknown'


def diagnostic(closed):
    groups={'current_matching_policy':[],'legacy_or_mixed_policy':[]}
    for t in closed:
        if isinstance(t,dict):
            groups['current_matching_policy' if certifiable_trade(t) else 'legacy_or_mixed_policy'].append(t)
    output={}
    for label,rows in groups.items():
        valid=[(t,d) for t in rows if (d:=decompose(t)) is not None]
        exits={}
        for t,d in valid:
            category=exit_group(t)
            group=exits.setdefault(category,{'closed':0,'net_pnl_gbp':0.})
            group['closed']+=1;group['net_pnl_gbp']+=d['net']
        for g in exits.values():g['net_pnl_gbp']=round(g['net_pnl_gbp'],4)
        output[label]=dict(closed=len(rows),decomposed=len(valid),
            unknown_or_inconsistent=len(rows)-len(valid),
            gross_price_pnl_gbp=round(sum(d['gross'] for _,d in valid),4) if valid else None,
            modeled_cost_drag_gbp=round(sum(d['drag'] for _,d in valid),4) if valid else None,
            decomposed_net_pnl_gbp=round(sum(d['net'] for _,d in valid),4) if valid else None,
            gross_wins=sum(d['gross']>0 for _,d in valid),
            net_wins=sum(d['net']>0 for _,d in valid),
            cost_erased_gross_wins=sum(d['cost_flipped'] for _,d in valid),
            by_exit=exits)
    return dict(cohorts=output,
        note='Descriptive recorded CLOSED GBP only; gross movement less recorded modeled entry/exit costs. Totals cover decomposed rows only. Mixed history cannot certify the current policy. Does not establish why repairs or strategy caused losses.')
