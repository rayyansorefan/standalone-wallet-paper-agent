"""Existing GBP positions: five-minute observation, capped adds and protection."""
import datetime as dt
import copy
import math
import unittest
from unittest import mock

from agent import core
from agent.position_management import (
    ADD_THRESHOLD_NET_ROI_PCT, EXPLORATION_TOTAL_CAP, REINFORCED_TOTAL_CAP,
    confirmed_rising, addition_amount, net_roi, apply_add
)

UTC=dt.timezone.utc
T=dt.datetime(2026,10,17,14,30,tzinfo=UTC)
W='A'*32
POOL='B'*32


def fresh_position(now=T):
    return {'wallet':W,'token':POOL,'pool_name':'WIN / SOL',
            'opened_at':(now-dt.timedelta(minutes=20)).isoformat(timespec='seconds'),
            'entry_price_usd':1.,'last_mark_price_usd':1.,
            'notional_gbp':10.,'cost_gbp':10.1,
            'additions':[], 'signal_id':'original-trade',
            'recent_marks':[], 'position_action':'NEW_POSITION'}


def prime(state, values=(1.08,1.11,1.14), end=T):
    p=state['positions'][0]
    for k,price in enumerate(values):
        at=end-dt.timedelta(minutes=(len(values)-1-k)*5)
        core.maintain_positions(state,{POOL:price},at)
    return p


def profile(tier='exploration'):
    return {'reinforcement_tier':tier,'risk_fraction':.005 if tier=='exploration' else .015}


class WinnerManagement(unittest.TestCase):
    def setUp(self):
        self.state=core.blank_state()
        self.state['cash_gbp']=1989.9
        self.state['positions']=[fresh_position()]
        self.now=T
        self.state['research']={'strategies_v1':{'cash_usd':2000.,'closed':[]}}

    def test_consecutive_five_minute_price_marks_confirm_trend_and_protect_winner(self):
        p=prime(self.state)
        self.assertTrue(confirmed_rising(p,T))
        self.assertGreater(net_roi(p,1.14),ADD_THRESHOLD_NET_ROI_PCT)
        self.assertIsNotNone(p.get('trailing_stop_price_usd'))
        self.assertGreater(p['trailing_stop_price_usd'],1.)
        self.assertLess(p['trailing_stop_price_usd'],1.14)
        self.assertEqual(len(p['recent_marks']),3)
        self.assertEqual(len(self.state['positions']),1)
        self.assertEqual(p['position_action'],'HOLD_PROTECTED')

    def test_strong_confirmed_position_runs_past_fixed_twenty_percent_target(self):
        prime(self.state,(1.16,1.20,1.30))
        self.assertEqual(len(self.state['closed']),0)
        self.assertEqual(len(self.state['positions']),1)
        self.assertGreater(self.state['positions'][0]['last_net_roi_pct'],20)
        self.assertGreater(self.state['positions'][0]['trailing_stop_price_usd'],1.15)

    def test_unconfirmed_single_spike_still_takes_profit(self):
        core.maintain_positions(self.state,{POOL:1.35},T)
        self.assertEqual(len(self.state['positions']),0)
        self.assertEqual(len(self.state['closed']),1)
        self.assertIn('20% paper take profit',self.state['closed'][0]['exit_reason'])

    def test_add_once_after_strong_rising_marks_with_current_safety_pass_and_cash(self):
        p=prime(self.state)
        eq=core.equity(self.state,{POOL:1.14})
        old_cash=self.state['cash_gbp']
        old_units=p['notional_gbp']/p['entry_price_usd']
        with mock.patch.object(core,'wallet_stats',return_value=profile()):
            added=core.reinforce_open_winners(self.state,{POOL:1.14},{POOL:T},T,{POOL},set())
        self.assertEqual(added,1)
        self.assertLess(self.state['cash_gbp'],old_cash)
        self.assertEqual(len(p['additions']),1)
        self.assertLessEqual(p['notional_gbp'],eq*EXPLORATION_TOTAL_CAP+0.01)
        self.assertAlmostEqual(p['notional_gbp'],13.,places=2)
        self.assertGreater(p['entry_price_usd'],1.)
        self.assertLess(p['entry_price_usd'],1.14)
        self.assertAlmostEqual(p['cost_gbp'],13.13,places=2)
        after_units=p['notional_gbp']/p['entry_price_usd']
        self.assertAlmostEqual(after_units,old_units+p['additions'][0]['notional_gbp']/1.14,places=6)
        self.assertEqual(self.state['research']['strategies_v1']['cash_usd'],2000)
        self.assertEqual(len(self.state['closed']),0)
        self.assertEqual(self.state['decisions'][-1]['action'],'PAPER_ADD_WINNER')
        self.assertEqual(core.reinforce_open_winners(self.state,{POOL:1.14},{POOL:T},T,{POOL},set()),0)

    def test_position_topups_scale_from_thirty_to_fifty_percent(self):
        scenarios=[
            ((1.08,1.11,1.14),3.,'30%'),
            ((1.09,1.13,1.19),4.,'40%'),
            ((1.09,1.17,1.25),5.,'50%'),
        ]
        for marks,expected,label in scenarios:
            with self.subTest(label=label):
                s=copy.deepcopy(self.state)
                prime(s,marks)
                with mock.patch.object(core,'wallet_stats',return_value=profile()):
                    count=core.reinforce_open_winners(
                        s,{POOL:marks[-1]},{POOL:T},T,{POOL},set())
                self.assertEqual(count,1)
                pos=s['positions'][0]
                self.assertAlmostEqual(pos['notional_gbp'],10+expected,places=2)
                self.assertAlmostEqual(pos['additions'][0]['notional_gbp'],expected,places=2)
                self.assertIn(label,s['decisions'][-1]['reason'])
                self.assertEqual(len(pos['additions']),1)
                self.assertEqual(len(s['research']['strategies_v1']['closed']),0)

    def test_add_does_not_inflate_larger_position_or_exceed_account_cap(self):
        s=copy.deepcopy(self.state)
        p=s['positions'][0]
        p.update(notional_gbp=19.5,cost_gbp=19.695)
        s['cash_gbp']=1980.305
        prime(s,(1.08,1.11,1.25))
        with mock.patch.object(core,'wallet_stats',return_value=profile()):
            count=core.reinforce_open_winners(
                s,{POOL:1.25},{POOL:T},T,{POOL},set())
        self.assertEqual(count,0)
        self.assertEqual(p.get('additions'),[])
        self.assertEqual(s['cash_gbp'],1980.305)

    def test_trailing_stop_exits_held_run_and_preserves_correct_net_accounting(self):
        p=prime(self.state)
        with mock.patch.object(core,'wallet_stats',return_value=profile()):
            core.reinforce_open_winners(self.state,{POOL:1.14},{POOL:T},T,{POOL},set())
        paid=p['cost_gbp']
        notional=p['notional_gbp']
        entry=p['entry_price_usd']
        cash=self.state['cash_gbp']
        px=p['trailing_stop_price_usd']-.001
        core.maintain_positions(self.state,{POOL:px},T+dt.timedelta(minutes=5))
        self.assertFalse(self.state['positions'])
        close=self.state['closed'][-1]
        expected=notional*px/entry*(1-core.COST_PER_SIDE)-paid
        self.assertAlmostEqual(close['net_pnl_gbp'],expected,places=3)
        self.assertAlmostEqual(self.state['cash_gbp'],cash+close['proceeds_gbp'],places=4)
        self.assertEqual(len(close['additions']),1)
        self.assertIn('trailing stop',close['exit_reason'])

    def test_no_add_on_unverified_pool_sender_sell_stale_price_or_weak_trend(self):
        for safe,sells,seen in [
            (set(),set(),T),
            ({POOL},{(W,POOL)},T),
            ({POOL},set(),T-dt.timedelta(minutes=6))
        ]:
            state=copy.deepcopy(self.state)
            p=prime(state)
            with mock.patch.object(core,'wallet_stats',return_value=profile()):
                added=core.reinforce_open_winners(state,{POOL:1.14},{POOL:seen},T,safe,sells)
            self.assertEqual(added,0)
            self.assertEqual(len(p['additions']),0)
            self.assertEqual(state['cash_gbp'],1989.9)

    def test_no_add_on_stalled_falling_prices_or_unpriced_position(self):
        p=prime(self.state,(1.08,1.13,1.11))
        with mock.patch.object(core,'wallet_stats',return_value=profile()):
            self.assertEqual(core.reinforce_open_winners(self.state,{POOL:1.11},{POOL:T},T,{POOL},set()),0)
        old=copy.deepcopy(p)
        core.maintain_positions(self.state,{},T+dt.timedelta(minutes=5))
        self.assertEqual(self.state['positions'][0]['last_mark_price_usd'],old['last_mark_price_usd'])
        self.assertEqual(self.state['positions'][0]['position_action'],'UNPRICED_HOLD')

    def test_sender_suspension_blocks_further_exposure(self):
        prime(self.state)
        for tier in ('suspended','exploration'):
            with mock.patch.object(core,'wallet_stats',return_value={'reinforcement_tier':tier,'risk_fraction':0}):
                self.assertEqual(core.reinforce_open_winners(self.state,{POOL:1.14},{POOL:T},T,{POOL},set()),0)

    def test_no_add_if_opened_fewer_than_ten_minutes_ago(self):
        p=self.state['positions'][0]
        p['opened_at']=(T-dt.timedelta(minutes=8)).isoformat()
        prime(self.state)
        with mock.patch.object(core,'wallet_stats',return_value=profile()):
            self.assertEqual(core.reinforce_open_winners(self.state,{POOL:1.14},{POOL:T},T,{POOL},set()),0)

    def test_reinforced_wallet_caps_at_one_point_five_percent_not_unbounded(self):
        p=prime(self.state)
        with mock.patch.object(core,'wallet_stats',return_value=profile('reinforced_2')):
            self.assertEqual(core.reinforce_open_winners(self.state,{POOL:1.14},{POOL:T},T,{POOL},set()),1)
        eq=core.equity(self.state,{POOL:1.14})
        self.assertLessEqual(p['notional_gbp'],eq*REINFORCED_TOTAL_CAP+0.05)
        self.assertEqual(len(p['additions']),1)

    def test_legacy_open_positions_do_not_backfill_invented_momentum(self):
        pos=self.state['positions'][0]
        pos.pop('recent_marks')
        pos.pop('additions')
        core.maintain_positions(self.state,{POOL:1.12},T)
        with mock.patch.object(core,'wallet_stats',return_value=profile()):
            self.assertEqual(core.reinforce_open_winners(self.state,{POOL:1.12},{POOL:T},T,{POOL},set()),0)
        self.assertEqual(len(pos['recent_marks']),1)

    def test_six_hour_stop_and_twelve_percent_loss_remain_independent_protections(self):
        s=copy.deepcopy(self.state)
        core.maintain_positions(s,{POOL:.85},T)
        self.assertEqual(len(s['closed']),1)
        self.assertIn('stop loss',s['closed'][0]['exit_reason'])
        s=copy.deepcopy(self.state)
        s['positions'][0]['opened_at']=(T-dt.timedelta(hours=7)).isoformat()
        core.maintain_positions(s,{POOL:1.05},T)
        self.assertEqual(len(s['closed']),1)
        self.assertIn('6-hour',s['closed'][0]['exit_reason'])

    def test_rising_marks_must_be_independent_and_well_spaced(self):
        p=self.state['positions'][0]
        for minute,price in [(0,1.08),(1,1.10),(2,1.15)]:
            core.maintain_positions(self.state,{POOL:price},T+dt.timedelta(minutes=minute))
        self.assertFalse(confirmed_rising(p,T+dt.timedelta(minutes=2)))
        with mock.patch.object(core,'wallet_stats',return_value=profile()):
            self.assertEqual(core.reinforce_open_winners(self.state,{POOL:1.15},
              {POOL:T+dt.timedelta(minutes=2)},T+dt.timedelta(minutes=2),{POOL},set()),0)


    def test_three_declining_fresh_prices_cut_loser_before_twelve_percent_threshold(self):
        for k,px in enumerate((.99,.97,.95)):
            core.maintain_positions(self.state,{POOL:px},T+dt.timedelta(minutes=5*k))
            if k<2:
                self.assertEqual(len(self.state['positions']),1)
        self.assertEqual(len(self.state['positions']),0)
        self.assertEqual(len(self.state['closed']),1)
        self.assertIn('early loss exit',self.state['closed'][0]['exit_reason'])
        self.assertGreater(self.state['closed'][0]['roi_pct'],-12)

    def test_isolated_loss_never_causes_unconfirmed_early_exit(self):
        core.maintain_positions(self.state,{POOL:.96},T)
        self.assertEqual(len(self.state['positions']),1)
        self.assertEqual(len(self.state['closed']),0)

    def test_early_loss_requires_real_five_minute_spacing(self):
        for k,px in enumerate((.99,.97,.95)):
            core.maintain_positions(self.state,{POOL:px},T+dt.timedelta(minutes=k))
        self.assertEqual(len(self.state['positions']),1)

if __name__=='__main__':
    unittest.main()
