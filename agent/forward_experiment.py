"""Predeclared paired PAPER trial, never a source of account allocation.

Both arms share observed quotes, universe, fees, carry, sizing and exit engine.
Only challenger admission differs. No backfill, API calls or risk promotion.
"""
import copy
import datetime as dt
import hashlib
from pathlib import Path

KEY = 'forward_experiment_v1'
ARCHIVE_KEY = 'forward_experiment_epochs_v1'
ACTIVE_VERSION = 'paired-pullback-3'
PREVIOUS_VERSION = 'paired-pullback-2'
LEGACY_VERSION = 'paired-pullback-1'
MIGRATABLE_VERSIONS = (LEGACY_VERSION,PREVIOUS_VERSION)
DAYS = 28
LOSS_BUDGET_USD = 40.


def source_hash():
    root = Path(__file__).parent
    return hashlib.sha256(b''.join((root/name).read_bytes() for name in
                          ('strategies.py','strategy_lab.py','forward_experiment.py'))).hexdigest()


def pullback_entry(setup, direction, f, quote):
    """Continuation only after a completed prior-bar pullback and reclaim.

    This is a falsifiable hypothesis, not a predicted profitable setup. Existing
    momentum/cost/news/risk gates still apply; no fresh-buying fade inference.
    """
    if setup not in ('momentum_long','momentum_short'):
        return False
    try:
        fast = f['previous_fast']
        touched = f['previous_low'] <= fast if direction == 1 else f['previous_high'] >= fast
        return (touched and direction*(f['previous']-fast) <= 0 and
                direction*(f['close']-f['ema_fast']) > 0 and
                abs(f['close']-f['ema_fast']) <= f['atr'] and
                (quote['ask']-quote['bid'])/quote['mid'] <= .001)
    except (KeyError, TypeError, ZeroDivisionError):
        return False


def _equity(book, quotes):
    from .strategies import exit_value
    p = book.get('position')
    if p and p['symbol'] not in quotes:
        return None
    return book['cash_usd'] + (exit_value(p,quotes[p['symbol']])[1]+
                              p['entry_fees']+p['carry_usd'] if p else 0.)


def _metrics(book):
    rows = book.get('closed',[])
    gains = sum(max(0,t['net_usd']) for t in rows)
    losses = -sum(min(0,t['net_usd']) for t in rows)
    wins = sum(t['net_usd']>0 for t in rows)
    return dict(closed=len(rows), wins=wins, losses=sum(t['net_usd']<0 for t in rows),
                net_usd=round(sum(t['net_usd'] for t in rows),6),
                equity_usd=round(book['equity_usd'],6),
                profit_factor=round(gains/losses,4) if losses else None,
                win_rate_pct=round(100*wins/len(rows),2) if rows else None,
                stress_net_usd=round(sum(t['stress_net_usd'] for t in rows),6),
                entry_hour_clusters=len({t['opened_at'][:13] for t in rows}),
                entry_days=len({t['opened_at'][:10] for t in rows}),
                open_positions=int(bool(book.get('position'))),
                drawdown_pct=book['max_drawdown_pct'],
                entry_block=book.get('experiment_entry_block'),
                status=book.get('status'),
                missing_exit_feature_cycles=book.get('missing_exit_feature_cycles',0),
                missing_mark_cycles=book.get('missing_mark_cycles',0))


def advance(state, now, quotes, indicators, eligible):
    from . import strategies as engine
    research = state.setdefault('research',{})
    # Work on a private copy: a failed arm never commits a half-paired cycle.
    trial = copy.deepcopy(research.get(KEY))
    digest = source_hash()
    # Preserve invalidated pre-stabilisation epochs verbatim, then begin one
    # separately versioned epoch against the held-candle-complete source.
    # An invalidated epoch with an open position remains active only for exit
    # management; it is archived after every arm is flat. Epoch 3 never
    # auto-rolls after later drift.
    arms=(trial or {}).get('arms') or {}
    flat=not any(isinstance(arm,dict) and arm.get('position')
                 for arm in arms.values())
    if (trial and trial.get('version') in MIGRATABLE_VERSIONS and
            trial.get('invalidated_at') and flat):
        archives = research.setdefault(ARCHIVE_KEY,[])
        identity = (trial.get('version'),trial.get('registered_at'),
                    trial.get('source_sha256'))
        if not any((row.get('version'),row.get('registered_at'),
                    row.get('source_sha256')) == identity for row in archives
                   if isinstance(row,dict)):
            archived = copy.deepcopy(trial)
            archived['archived_at'] = now.isoformat()
            archived['archive_reason'] = 'FROZEN_SOURCE_INVALIDATED'
            archives.append(archived)
            research[ARCHIVE_KEY] = archives[-10:]
        trial = None
    if trial is None:
        trial = dict(version=ACTIVE_VERSION, registered_at=now.isoformat(),
                     end_at=(now+dt.timedelta(days=DAYS)).isoformat(),
                     source_sha256=digest, paper_only=True, arms={}, cycles=0,
                     loss_budget_usd=LOSS_BUDGET_USD, automatic_promotion=False,
                     hypothesis='Completed-bar pullback/reclaim admission improves net results versus existing futures rules on the same feed.',
                     baseline='Fresh isolated replica of momentum-fade-2, including its existing feedback; NOT the historical GBP account.',
                     comparison='Equal $2000 simulated starts, same quote batch, existing fees/slippage/carry/exits/risk, only entry filter differs.',
                     predecessor_version=PREVIOUS_VERSION,
                     restart_reason='SEPARATE_EPOCH_AFTER_STABLE_SCAN_ENGINEERING',
                     max_duration_days=DAYS)
        for name in ('baseline','pullback'):
            trial['arms'][name]=engine.initialize({},now)
    if trial.get('last_run') and now <= engine.stamp(trial['last_run']):
        return trial
    if digest != trial['source_sha256']:
        trial['invalidated_at']=trial.get('invalidated_at') or now.isoformat()
        trial['invalid_reason']='ECONOMIC_SOURCE_CHANGED_NO_AUTOMATIC_RESTART'
    ended = now >= engine.stamp(trial['end_at'])
    for name, book in trial['arms'].items():
        held=book.get('position')
        if held and held['symbol'] not in indicators:
            book['missing_exit_feature_cycles']=book.get('missing_exit_feature_cycles',0)+1
        if held and held['symbol'] not in quotes:
            book['missing_mark_cycles']=book.get('missing_mark_cycles',0)+1
        def guard():
            mark = _equity(book,quotes)
            if mark is not None and mark <= book['starting_usd']-LOSS_BUDGET_USD:
                book['experiment_entry_block']='LOSS_BUDGET_EXHAUSTED'
            if trial.get('invalidated_at'):
                book['experiment_entry_block']='SOURCE_CHANGED'
            elif ended and not book.get('experiment_entry_block'):
                book['experiment_entry_block']='FIXED_TRIAL_ENDED'
            return not book.get('experiment_entry_block') and mark is not None
        allowed = guard()
        isolated = {'research':{'strategies_v1':book,
                    'news_v1':copy.deepcopy(research.get('news_v1',{}))}}
        if not allowed:
            # Also prevents additions; existing observed exit management continues.
            isolated['research']['news_v1']['risk_off']=True
        def admit(setup,direction,f,q):
            # Re-check after this cycle's close/carry debit before a replacement entry.
            return guard() and (name=='baseline' or pullback_entry(setup,direction,f,q))
        engine.advance(isolated,now,quotes,indicators,eligible,candidate_filter=admit)
        guard()
        trial['arms'][name]=book
    metrics={name:_metrics(book) for name,book in trial['arms'].items()}
    a,b=metrics['baseline'],metrics['pullback']
    complete = ended and not any(m['open_positions'] for m in metrics.values())
    # Necessary descriptive hurdles only. Hour clusters are NOT proof of independence.
    hurdles = dict(complete=complete,
                   adequate_sample=b['closed']>=100 and b['entry_hour_clusters']>=100,
                   positive_net=b['net_usd']>0,
                   profit_factor=(b['profit_factor'] or 0)>1.3,
                   majority_wins=(b['win_rate_pct'] or 0)>50,
                   stress_positive=b['stress_net_usd']>0,
                   beats_baseline=b['equity_usd']>a['equity_usd'],
                   complete_observations=not any(m['missing_exit_feature_cycles'] or m['missing_mark_cycles'] for m in metrics.values()),
                   no_loss_stop=not any(m['entry_block']=='LOSS_BUDGET_EXHAUSTED' for m in metrics.values()))
    status = ('INVALIDATED' if trial.get('invalidated_at') else
              'REVIEW_REQUIRED_NOT_VALIDATED' if all(hurdles.values()) else
              'COMPLETED_NO_PROMOTION' if complete else
              'LOSS_LIMITED' if any(m['entry_block']=='LOSS_BUDGET_EXHAUSTED' for m in metrics.values()) else
              'COLLECTING')
    trial.update(last_run=now.isoformat(),cycles=trial['cycles']+1,status=status)
    trial['summary']=dict(status=status,last_run=now.isoformat(),registered_at=trial['registered_at'],
                         end_at=trial['end_at'],source_sha256=trial['source_sha256'],
                         arms=metrics,delta_equity_usd=round(b['equity_usd']-a['equity_usd'],6),
                         hurdles=hurdles,automatic_promotion=False,
                         note='Prospective USD simulations only. Quote-sampled stops can gap. Descriptive hurdles do not establish statistical independence, confidence or profitable learning.')
    research[KEY]=trial
    return trial


def safe_advance(state, now, quotes, indicators, eligible):
    try:
        result=advance(state,now,quotes,indicators,eligible)
        state['research'].pop('forward_experiment_error',None)
        return result
    except Exception as exc:
        # Keep the main engine and previously committed trial intact.
        state.setdefault('research',{})['forward_experiment_error']={
            'at':now.isoformat(),'type':type(exc).__name__,'status':'EXPERIMENT_FAILED'}
        return None
