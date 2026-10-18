"""Read-only historical strategy tournament: NO orders, no ledger mutation.

Tests market-condition proxies on already persisted discovery quotes. Not executable
backtesting, not a win-rate promise. Historical results are exploratory and can be
used to specify (not validate) a new, separately registered prospective experiment.
"""
import argparse
import datetime as dt
import json
import math
from collections import defaultdict
from pathlib import Path

HORIZONS_MIN = (5, 30, 60)
ENTRY_COST = 0.01
EXIT_COST = 0.01
MAX_FUTURE_LAG_MIN = 7
PER_POOL_COOLDOWN_MIN = 60
VERSION = 'EXPLORE_QUOTES_20261018_V1'

def number(x):
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None

def time_of(x):
    try:
        v = dt.datetime.fromisoformat(str(x).replace('Z', '+00:00'))
        return v if v.tzinfo else None
    except (ValueError, TypeError):
        return None

def measures(row):
    five = number(row.get('change_5m_pct'))
    hour = number(row.get('change_1h_pct'))
    liq = number(row.get('liquidity_usd'))
    vol24 = number(row.get('volume_24h_usd'))
    vol1 = number(row.get('volume_1h_usd'))
    buys = number(row.get('buys_1h'))
    sells = number(row.get('sells_1h'))
    pace = 24 * vol1 / vol24 if vol1 is not None and vol24 and vol24 > 0 else None
    share = buys / (buys + sells) if buys is not None and sells is not None and buys + sells > 0 else None
    return five, hour, liq, pace, share

def eligible(row, style):
    # Historical PASS is only a necessary prerequisite for a quoted proxy.
    # It cannot certify current Rugcheck, exit liquidity or executable swap price.
    if row.get('token_safety') != 'PASS':
        return False
    five, hour, liq, pace, buys = measures(row)
    if style == 'screened_quote_baseline':
        return True
    if five is None or hour is None:
        return False
    if style == 'positive_momentum':
        return five > 0 and hour > 0
    if style == 'strong_breakout':
        return five > 2 and hour > 5
    if style == 'moderate_momentum':
        return 0.2 <= five <= 2 and 1 <= hour <= 10
    if style == 'uptrend_pullback':
        return hour > 2 and -3 < five < 0
    if style == 'countertrend_rebound':
        return five > .5 and hour < 0
    if style == 'dip_reversal':
        return five < -2 and hour < 0
    if style == 'buy_pressure':
        return buys is not None and buys >= .6 and liq is not None and liq >= 250_000
    if style == 'liquid_trend':
        return liq is not None and liq >= 500_000 and five > 0 and hour > 0
    if style == 'relative_volume_trend':
        return pace is not None and pace >= 1.2 and five > 0 and hour > 0
    if style == 'bespoke_flow_reclaim_v0_SHADOW_ONLY':
        # Predeclared hypothesis for FRESH future testing; NEVER promote based
        # on its in-sample score. No change to the actual entry/exit engine.
        return (liq is not None and liq >= 250_000 and pace is not None
                and pace >= 1.2 and buys is not None and buys >= .58
                and .4 <= five <= 3 and 2 <= hour <= 12)
    raise ValueError('Unknown research filter: ' + str(style))

STYLES = (
    'screened_quote_baseline', 'positive_momentum', 'strong_breakout',
    'moderate_momentum', 'uptrend_pullback', 'countertrend_rebound',
    'dip_reversal', 'buy_pressure', 'liquid_trend',
    'relative_volume_trend', 'bespoke_flow_reclaim_v0_SHADOW_ONLY',
)

def evaluate(observations, style, horizon):
    """One indicative decision per pool per 60m; no hindsight feature use.

    Match the first later timestamp within [horizon, horizon+7] minutes.
    Missing marks counted and excluded, never booked as zero/win.
    Quote outcomes are NOT fills, and marks across pools may be correlated.
    """
    groups = defaultdict(list)
    for row in observations:
        price, when = number(row.get('price_usd')), time_of(row.get('at'))
        if row.get('pool') and price is not None and price > 0 and when:
            groups[row['pool']].append((when, price, row))
    matches, missing = [], 0
    for pool, records in groups.items():
        records.sort(key=lambda x: x[0])
        last_admitted = None
        for i, (when, entry, row) in enumerate(records):
            if not eligible(row, style):
                continue
            if last_admitted and (when - last_admitted).total_seconds() < PER_POOL_COOLDOWN_MIN * 60:
                continue
            last_admitted = when
            end_earliest = when + dt.timedelta(minutes=horizon)
            end_latest = end_earliest + dt.timedelta(minutes=MAX_FUTURE_LAG_MIN)
            later = next(((mark, quote) for mark, quote, _ in records[i + 1:]
                          if end_earliest <= mark <= end_latest), None)
            if later is None:
                missing += 1
                continue
            # Quote ratio with the EXISTING paper account's modelled 1% on each
            # side: pay (1+entry cost) to enter, receive (1-exit cost) to exit.
            exit_at, exit_price = later
            gross = 100 * (exit_price / entry - 1)
            net = 100 * ((exit_price / entry) * (1 - EXIT_COST) / (1 + ENTRY_COST) - 1)
            matches.append((pool, when.date().isoformat(), net, gross, exit_at))
    n = len(matches)
    gains = sum(max(0, x[2]) for x in matches)
    losses = -sum(min(0, x[2]) for x in matches)
    days = len({x[1] for x in matches})
    result = dict(style=style, horizon_minutes=horizon, evaluated_quotes=n,
                  missing_future_quotes=missing, distinct_pools=len({x[0] for x in matches}),
                  distinct_entry_days=days, positive_net_quotes=sum(x[2] > 0 for x in matches),
                  avg_gross_quote_roi_pct=round(sum(x[3] for x in matches) / n, 4) if n else None,
                  avg_net_quote_roi_pct=round(sum(x[2] for x in matches) / n, 4) if n else None,
                  net_positive_fraction=round(sum(x[2] > 0 for x in matches) / n, 4) if n else None,
                  quote_profit_factor=round(gains / losses, 4) if losses else None,
                  validation='EXPLORATORY_NOT_OUT_OF_SAMPLE',
                  paper_orders=0, strategy_promotion=False)
    return result

def analyze(state):
    observations = ((state.get('research') or {}).get('pool_observations') or [])
    if not isinstance(observations, list):
        raise TypeError('pool_observations must be a list')
    timestamps = sorted({row.get('at') for row in observations if isinstance(row, dict) and row.get('at')})
    winners = [x for x in state.get('closed', []) if number(x.get('net_pnl_gbp')) is not None
               and number(x.get('net_pnl_gbp')) > 0]
    winners.sort(key=lambda row: row.get('exit_at') or '')
    last11 = winners[-11:]
    rows = [evaluate(observations, style, horizon)
            for style in STYLES for horizon in HORIZONS_MIN]
    return dict(version=VERSION, source='Persisted discovery pool observations',
                oldest_observation=timestamps[0] if timestamps else None,
                newest_observation=timestamps[-1] if timestamps else None,
                stored_rows=len(observations), distinct_observation_timestamps=len(timestamps),
                recent_winner_context=dict(
                    count=len(last11),
                    mixed_or_legacy=sum(not x.get('policy_epoch') for x in last11),
                    net_gbp=round(sum(x['net_pnl_gbp'] for x in last11), 4)),
                cost_model='1% adverse at entry, 1% adverse at exit; quote-based estimates',
                methods='PASS-at-entry only; first subsequent 5/30/60m quoted mark (+7m tolerance); once per pool per hour',
                results=rows,
                coverage_limitation='Rolling buffer, short time coverage, repeated/correlated pools, unequal safety coverage; no executions.',
                status='RESEARCH_ONLY_NO_PROMOTION',
                independent_forward_validation=False)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path('state/state.json'))
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding='utf8'))
    print(json.dumps(analyze(state), indent=2, allow_nan=False))

if __name__ == '__main__':
    main()
