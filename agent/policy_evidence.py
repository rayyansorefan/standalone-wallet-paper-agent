"""Explicit prospective economic policy epoch, never backfilled onto old trades.

Increment EPOCH, ENTRY_ID and/or EXIT_ID when an ECONOMIC rule changes.
Source-code commits are recorded separately: a diagnostics bug fix should not
silently relabel preexisting strategy results as a new economic experiment.
"""
import hashlib
import json
import os

EPOCH='GBP_WALLET_COPY_20261017_AUDITED_EPOCH_1'
ENTRY_ID='GBP_ENTRY_TECHNICAL_NEWS_WALLET_V1'
EXIT_ID='GBP_EXIT_NET_WARN_2_STOP_4P5_6H_V1'
DATA_SOURCE_ID='GECKO_VERIFIED_SWAPS_FREE_DEX_QUOTES_V1'
MODELLING_ID='GBP_PAPER_POOL_RATIO_1PCT_EACH_SIDE_V1'
CONFIG={
    'entry_id':ENTRY_ID,'exit_id':EXIT_ID,'data_source_id':DATA_SOURCE_ID,
    'model_id':MODELLING_ID,'paper_only':True,'starting_gbp':2000,
    'quote_cadence_minutes':5,'minimum_wallet_trades':3,
    'minimum_liquidity_usd':100000,'minimum_24h_volume_usd':150000,
    'minimum_pool_age_hours':24,'minimum_momentum_5m_pct':0,
    'minimum_momentum_1h_pct':0,'maximum_momentum_5m_pct':12,
    'maximum_momentum_1h_pct':40,'max_fresh_signal_age_seconds':240,
    'base_position_equity_fraction':.005,'maximum_positions':5,
    'maximum_hold_hours':6,'risk_warning_net_roi_pct':-2,
    'exit_stop_net_roi_pct':-4.5,'trailing_winner_add_max_count':1,
    'position_add_relative_to_initial_range':[.3,.5],
    'fixed_modelled_transaction_cost_each_side':.01,
}
CONFIG_HASH=hashlib.sha256(json.dumps(CONFIG,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def execution_revision():
    """Workflow SHA is provenance, not proof of an executable venue fill."""
    return str(os.getenv('GITHUB_SHA') or 'LOCAL_UNSPECIFIED_REVISION')


def new_entry_tags():
    return {'policy_epoch':EPOCH,'entry_policy_id':ENTRY_ID,
            'entry_configuration_hash':CONFIG_HASH,
            'market_data_source_id':DATA_SOURCE_ID,
            'execution_model_id':MODELLING_ID,
            'entry_workflow_sha':execution_revision()}


def new_exit_tags():
    return {'exit_policy_id':EXIT_ID,'exit_configuration_hash':CONFIG_HASH,
            'exit_workflow_sha':execution_revision()}


def certifiable_trade(record):
    """Keep legacy and cross-epoch closes in reported P&L, OUT of new certificates."""
    return bool(isinstance(record,dict) and record.get('policy_epoch')==EPOCH and
                record.get('entry_policy_id')==ENTRY_ID and
                record.get('exit_policy_id')==EXIT_ID and
                record.get('entry_configuration_hash')==CONFIG_HASH and
                record.get('exit_configuration_hash')==CONFIG_HASH)
