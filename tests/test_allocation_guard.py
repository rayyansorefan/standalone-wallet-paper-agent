import copy
import datetime as dt
import unittest
from unittest.mock import patch
from agent import core
from agent.allocation_guard import update, KEY
from agent.policy_evidence import new_entry_tags,new_exit_tags

NOW=dt.datetime(2026,10,18,14,0,tzinfo=dt.timezone.utc)

def close(i,pnl=-.5):
    return dict(signal_id=str(i),wallet='wallet'+str(i),token='token'+str(i),
                exit_at=(NOW-dt.timedelta(minutes=10-i)).isoformat(),net_pnl_gbp=pnl,
                **new_entry_tags(),**new_exit_tags())

def state():
    s=core.blank_state();s['research']={};s['closed']=[close(i) for i in range(3)];return s


class AllocationGuard(unittest.TestCase):
    def test_different_wallets_and_pools_do_not_bypass_strategy_suspension(self):
        s=state();before=copy.deepcopy(s['closed']);g=update(s,NOW)
        self.assertEqual(g['status'],'SUSPENDED');self.assertFalse(g['new_entries_allowed'])
        self.assertEqual(s['closed'],before)

    def test_win_breaks_streak_before_trigger(self):
        s=state();s['closed'][1]=close(1,1)
        self.assertTrue(update(s,NOW)['new_entries_allowed'])

    def test_duplicate_and_future_records_do_not_create_three_losses(self):
        s=state();s['closed']=[close(0),close(0),close(0)]
        future=close(1);future['exit_at']=(NOW+dt.timedelta(hours=1)).isoformat()
        s['closed'].append(future)
        self.assertTrue(update(s,NOW)['new_entries_allowed'])
        self.assertEqual(update(s,NOW)['comparable_closes'],1)

    def test_legacy_mixed_evidence_is_not_current_policy(self):
        s=state()
        for t in s['closed']:t.pop('entry_configuration_hash')
        self.assertTrue(update(s,NOW)['new_entries_allowed'])

    def test_suspension_survives_winner_new_day_and_retention(self):
        s=state();first=update(s,NOW)['suspended_at']
        s['closed'].append(close(4,3))
        self.assertFalse(update(s,NOW+dt.timedelta(days=1))['new_entries_allowed'])
        s['closed']=[]
        self.assertEqual(update(s,NOW+dt.timedelta(days=30))['suspended_at'],first)
        self.assertFalse(s['research'][KEY]['new_entries_allowed'])

    def test_invalid_matching_record_fails_closed(self):
        s=state();s['closed'][0]['net_pnl_gbp']=float('nan')
        self.assertEqual(update(s,NOW)['status'],'EVIDENCE_UNAVAILABLE')
        self.assertFalse(s['research'][KEY]['new_entries_allowed'])

    def test_open_path_blocks_before_allocation_and_records_reason(self):
        s=state();cash=s['cash_gbp']
        ev=dict(wallet='new-wallet',token='new-token')
        with patch('agent.core.wallet_stats',side_effect=AssertionError('must not size')):
            core.maybe_open(s,ev,1,NOW,{})
        self.assertEqual(s['cash_gbp'],cash);self.assertEqual(s['positions'],[])
        self.assertEqual(s['decisions'][-1]['action'],'SKIP_POLICY_ALLOCATION')

    def test_additions_blocked_but_existing_position_can_close(self):
        s=state();p=dict(wallet='existing',token='held',notional_gbp=10,
                        entry_price_usd=1,cost_gbp=10.1)
        s['positions']=[p];cash=s['cash_gbp']
        self.assertEqual(core.reinforce_open_winners(s,{'held':1.2},{'held':NOW},NOW,{'held'},set()),0)
        self.assertEqual(s['cash_gbp'],cash)
        self.assertTrue(core.close_position(s,p,.9,'4.5% observed net paper stop loss'))
        self.assertEqual(s['positions'],[]);self.assertEqual(len(s['closed']),4)
        self.assertEqual(s['research'][KEY]['status'],'SUSPENDED')

    def test_chronological_order_not_storage_order(self):
        s=state();s['closed']=[close(5),close(0,2),close(4),close(3)]
        self.assertEqual(update(s,NOW)['current_loss_streak'],3)

    def test_never_changes_other_research_or_accounts(self):
        s=state();s['research']['strategies_v1']={'cash_usd':1900}
        s['research']['forward_experiment_v1']={'status':'COLLECTING'}
        before=copy.deepcopy(s);update(s,NOW)
        for k in ('cash_gbp','positions','closed'):self.assertEqual(s[k],before[k])
        for k in before['research']:self.assertEqual(s['research'][k],before['research'][k])
