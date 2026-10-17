"""Publish a minimal, public and read-only state for the JS visualiser."""
import json
from pathlib import Path


def publish_json(state, path='docs/state.json'):
    dst=Path(path)
    dst.parent.mkdir(parents=True,exist_ok=True)
    # Public repository: wallet sender addresses and trading history are visible.
    # The full deduplication list is unnecessary for the chart and is excluded.
    public={k:v for k,v in state.items() if k not in {'seen_trades'}}
    tmp=dst.with_suffix('.tmp')
    tmp.write_text(json.dumps(public,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf8')
    tmp.replace(dst)


def html_dashboard(s,path):
    """Legacy static-report helper, retained for backwards-compatible tests."""
    import html
    def esc(x):return html.escape(str(x),quote=True)
    html_body='<h1>Standalone Wallet Paper Research</h1><p>PAPER ONLY</p>'
    for d in s.get('decisions',[]):
        html_body+='<p>'+esc(d.get('action'))+' '+esc(d.get('reason'))+'</p>'
    Path(path).write_text('<!doctype html><html><meta charset="utf-8">'+html_body+'</html>',encoding='utf8')

def compact_health(state):
    """Small, public, non-sensitive health check for GitHub monitoring.

    Never expose secrets, sender identities, complete positions or account state.
    Missing fields remain explicitly unknown; a completed cycle is not proof of
    healthy feeds or profitable trading.
    """
    research=state.get('research') or {}
    main_health=state.get('cycle_health') or {}
    primary=research.get('primary_provider_v1') or {}
    whale=research.get('whale_v3') or {}
    futures=research.get('strategies_v1') or {}
    execution=state.get('execution') or {}
    status=state.get('last_status')
    opened=state.get('positions') or []
    closed=state.get('closed') or []
    last_cycle=state.get('last_run')
    # Aggregate only; do not publish wallet identities, token addresses or
    # individual saved transactions in the compact public health endpoint.
    recent_adds=[x for x in (state.get('decisions') or [])
                 if isinstance(x,dict) and x.get('action')=='PAPER_ADD_WINNER']
    position_management={
        'open_with_additions':sum(bool(p.get('additions')) for p in opened),
        'closed_with_additions':sum(bool(p.get('additions')) for p in closed),
        'open_additions':sum(len(p.get('additions') or []) for p in opened),
        'closed_additions':sum(len(p.get('additions') or []) for p in closed),
        'open_with_trailing_protection':sum(p.get('trailing_stop_price_usd') is not None for p in opened),
        'open_with_recorded_mark':sum(bool(p.get('last_mark_at')) for p in opened),
        'open_unpriced':sum(p.get('position_action')=='UNPRICED_HOLD' for p in opened),
        'open_loss_warnings':sum(bool(p.get('loss_warning_active')) for p in opened),
        'closed_at_4_5pct_stop':sum('4.5% observed net paper stop loss' in str(p.get('exit_reason','')) for p in closed),
        'net_loss_warning_pct':-2.0,
        'net_loss_exit_pct':-4.5,
        'last_add_at':recent_adds[-1].get('at') if recent_adds else None,
        'latest_cycle':last_cycle,
        'risk_policy':'ONE_30_TO_50_PCT_POSITION_TOPUP_ONLY_AFTER_3_RISING_MARKS'
    }
    return {
        'schema':1, 'paper_only':state.get('paper_only') is True,
        'last_run':state.get('last_run'),
        'last_data_at':state.get('last_data_at'),
        'cycle':state.get('completed_cycles'),
        'status':status,
        'cycle_health':main_health,
        'recent_errors':[] if status in ('OK','NO_ELIGIBLE_POOLS','NO_SAFE_POOLS','BOOTSTRAPPED_NO_TRADES')
                        else [{'at':e.get('at'),'error':str(e.get('error',''))[:200]}
                              for e in state.get('errors',[])[-6:] if isinstance(e,dict)],
        'position_management':position_management,
        'market_resilience':research.get('alternate_price_feed_v1') or {},
        'helius_rpc':research.get('helius_rpc_v1') or {'status':'NOT_CONFIGURED'},
        'primary_provider':{k:primary.get(k) for k in
                            ('http_status','requests','last_error','retry_at',
                             'rate_limit_strikes','last_success_at')},
        'whale':{'status':whale.get('status'),
                 'last_run':whale.get('last_run'),
                 'last_scan_errors':[str(x)[:160] for x in whale.get('last_scan_errors',[])[-3:]]},
        'futures':{'status':futures.get('status'),
                   'last_run':futures.get('last_run'),
                   'closed':len(futures.get('closed') or []),
                   'wins':(futures.get('summary') or {}).get('wins')},
        'original':{'closed':len(state.get('closed') or []),
                    'open_positions':len(state.get('positions') or [])},
        'execution':{k:execution.get(k) for k in
                     ('scheduler','scheduled_at','run_id','trigger_uid')},
        'note':'Diagnostic observations only; successful workflow != profitable trading.'
    }


def publish_health(state, path='docs/health.json'):
    """Atomic snapshot; no provider requests and no trading-state mutation."""
    dst=Path(path)
    dst.parent.mkdir(parents=True,exist_ok=True)
    tmp=dst.with_suffix('.tmp')
    tmp.write_text(json.dumps(compact_health(state),ensure_ascii=False,allow_nan=False,
                              indent=2),encoding='utf8')
    tmp.replace(dst)
