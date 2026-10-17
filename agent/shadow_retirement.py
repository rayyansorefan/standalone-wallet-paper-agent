"""Conservative, deterministic retirement gate for losing PAPER SHADOW experiments.

Negative research does not affect the real-world or original £2k paper account.
Historical outcomes and open shadow positions remain intact; retired strategies
simply cannot open *new* shadow positions until a reviewed policy change.
"""
MIN_CLOSES = 30
MIN_DAYS = 7
MIN_WALLETS = 4
MIN_POOLS = 3
MAX_PROFIT_FACTOR = .70
MAX_WIN_RATE_PCT = 35.


def retirement_check(report):
    """Return (retire, reason). No inference from incomplete samples."""
    n=report.get('closed',0)
    days=report.get('distinct_exit_days',report.get('distinct_days',0))
    wallets=report.get('distinct_wallets',0)
    pools=report.get('distinct_pools',0)
    pf=report.get('profit_factor')
    net=report.get('net_gbp')
    wins=report.get('wins',0)
    if not all(isinstance(x,(int,float)) for x in (n,days,wallets,pools,wins)):
        return False,'INSUFFICIENT_EVIDENCE'
    if n<MIN_CLOSES or days<MIN_DAYS or wallets<MIN_WALLETS or pools<MIN_POOLS:
        return False,'INSUFFICIENT_EVIDENCE'
    if not isinstance(net,(int,float)) or pf is None:
        return False,'INSUFFICIENT_EVIDENCE'
    if (net<0 and pf<=MAX_PROFIT_FACTOR and 100*wins/n<=MAX_WIN_RATE_PCT):
        return True,'PERSISTENT_NEGATIVE_FORWARD_SHADOW_OUTCOMES'
    return False,'NOT_RETIRED'


def update_retirements(research, reports, current, event_key='events', event_action='SHADOW_STRATEGY_RETIRED'):
    """Monotone retirement; changing the model must be an explicit code review."""
    retired=research.setdefault('retired_shadow_strategies',{})
    events=research.setdefault(event_key,[])
    at=current.isoformat(timespec='seconds')
    for name,report in reports.items():
        if name not in retired and retirement_check(report)[0]:
            retired[name]={'at':at,'reason':'PERSISTENT_NEGATIVE_FORWARD_SHADOW_OUTCOMES',
                           'closed':report['closed'],'days':report.get('distinct_exit_days',report.get('distinct_days')),
                           'net_gbp':report['net_gbp'],'profit_factor':report['profit_factor'],
                           'rule':'min30_closes_7days_4wallets_3pools_PF<=0.70_WinRate<=35'}
            events.append({'at':at,'action':event_action,'strategy':name,
                           'reason':retired[name]['reason']})
        if name in retired:
            report['status']='RETIRED_NEGATIVE_EVIDENCE'
            report['retired_at']=retired[name]['at']
            report['reason']=retired[name]['reason']
    research[event_key]=events[-300:]
    return retired
