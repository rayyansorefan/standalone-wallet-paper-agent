"""GBP policy-wide loss suspension; independent of wallet and pool identity.

This is a defensive allocation control, not a profitability certificate. It
never closes positions, rewrites history, resets balances or resumes by time.
"""
import datetime as dt
import math
from .policy_evidence import certifiable_trade, EPOCH

KEY='gbp_allocation_guard_v1'
VERSION='GBP_THREE_POLICY_LOSSES_V1'


def timestamp(value):
    try:
        t=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return t if t.tzinfo is not None else None
    except (ValueError,TypeError):return None


def update(state, current):
    guard=state.setdefault('research',{}).setdefault(KEY,{
        'version':VERSION,'registered_at':current.isoformat(),'status':'ACTIVE',
        'new_entries_allowed':True,'winner_additions_allowed':True,
        'reason':'No policy-wide suspension triggered',
        'resume_policy':'No timed reset. Requires separately reviewed prospective evidence and explicit versioned release; never erase the suspension.'})
    rows=[];seen=set();invalid=0
    for t in state.get('closed',[]):
        if not certifiable_trade(t):continue
        at=timestamp(t.get('exit_at'));sid=t.get('signal_id')
        value=t.get('net_pnl_gbp')
        if (at is None or not sid or isinstance(value,bool) or
                not isinstance(value,(int,float)) or not math.isfinite(value)):
            invalid+=1;continue
        if at>current or sid in seen:continue
        seen.add(sid);rows.append((at,str(sid),value))
    rows.sort(key=lambda x:(x[0],x[1]))
    streak=0
    for _,_,pnl in reversed(rows):
        if pnl>=0:break
        streak+=1
    guard.update(last_checked_at=current.isoformat(),evidence_policy_epoch=EPOCH,
                 comparable_closes=len(rows),current_loss_streak=streak,
                 current_policy_net_gbp=round(sum(r[2] for r in rows),4),
                 current_policy_wins=sum(r[2]>0 for r in rows),
                 invalid_evidence_records=invalid)
    # Once suspended, later winners from already-open holdings, time passage,
    # rolling retention or an epoch rename must not silently reopen allocation.
    if guard.get('suspended_at'):
        guard.update(status='SUSPENDED',new_entries_allowed=False,winner_additions_allowed=False)
        return guard
    if invalid:
        guard.update(status='EVIDENCE_UNAVAILABLE',new_entries_allowed=False,
                     winner_additions_allowed=False,reason='Invalid matching-policy close evidence; entries fail closed')
    elif streak>=3:
        guard.update(status='SUSPENDED',suspended_at=current.isoformat(),
                     trigger_last_exit_at=rows[-1][0].isoformat(),
                     trigger_loss_streak=streak,trigger_policy_epoch=EPOCH,
                     trigger_net_gbp=round(sum(r[2] for r in rows[-3:]),4),
                     new_entries_allowed=False,winner_additions_allowed=False,
                     reason='Three consecutive net losses in the same GBP policy, across all wallets and tokens')
    else:
        guard.update(status='ACTIVE',new_entries_allowed=True,winner_additions_allowed=True,
                     reason='No policy-wide suspension triggered')
    return guard
