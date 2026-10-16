"""Full engine regression checks for the supplied adaptive integration."""
import copy
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent import core, adaptive


class AdaptiveIntegration(unittest.TestCase):
    def test_full_cycle_conflicts_preserve_account_and_history(self):
        now = dt.datetime.now(core.UTC)
        wallet, token, mint = 'A'*32, 'B'*32, 'C'*32
        state = core.blank_state()
        state.update(last_run=(now-dt.timedelta(minutes=5)).isoformat(), completed_cycles=77)
        state['observed'][wallet] = {'count': 4}
        # An unrelated existing position remains monitored, never reinitialized.
        state['positions'] = [dict(wallet='D'*32, token=token, pool_name='existing',
            opened_at=(now-dt.timedelta(minutes=10)).isoformat(), entry_price_usd=1,
            last_mark_price_usd=0.9, notional_gbp=10, cost_gbp=10.1, signal_id='preserved')]
        state['cash_gbp'] = 1989.9
        old_closed = dict(wallet='D'*32,token=token,signal_id='old-close',
            net_pnl_gbp=-0.2,roi_pct=-2,exit_at=(now-dt.timedelta(days=1)).isoformat())
        state['closed'] = [old_closed]
        raw_pool = dict(id='solana_'+token, relationships={'base_token':{'data':{'id':'solana_'+mint}}},
            attributes=dict(address=token,name='SAMPLE/SOL',reserve_in_usd='400000',
            volume_usd={'h24':'800000','h1':'10000'},price_change_percentage={'h24':'12','h1':'1'},
            base_token_price_usd='1',pool_created_at=(now-dt.timedelta(days=5)).isoformat()))
        trades = [dict(attributes=dict(tx_hash='conflict-'+kind,tx_from_address=wallet,kind=kind,
            block_timestamp=(now-dt.timedelta(seconds=30-i)).isoformat(),volume_in_usd='200'))
            for i,kind in enumerate(('buy','sell'))]
        def fetch(path, params=None):
            return {'data':[raw_pool] if 'trending_pools' in path else trades}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json'; core.save(state,path)
            result=core.run_cycle(fetch=fetch,path=path,screen_token=lambda _:True)
        self.assertEqual(result['initialized_at'],state['initialized_at'])
        self.assertEqual(result['starting_gbp'],2000)
        self.assertEqual(result['cash_gbp'],state['cash_gbp'])
        self.assertEqual(result['closed'],[old_closed])
        self.assertEqual(result['positions'][0]['signal_id'],'preserved')
        self.assertEqual(result['positions'][0]['last_mark_price_usd'],1)
        self.assertEqual(result['completed_cycles'],78)
        self.assertEqual(result['last_status'],'OK')
        self.assertFalse(any(d['action']=='PAPER_BUY' for d in result['decisions']))
        self.assertTrue(any('Conflicting' in d['reason'] for d in result['decisions']))
        self.assertEqual(len(result['research']['signals']),2)
        self.assertEqual(result['research']['pool_observations'][0]['volume_1h_usd'],10000)
        self.assertEqual(result['research']['shadow_positions'],[])

    def test_actual_sizing_clamped_and_suspension_cannot_be_bypassed(self):
        now=dt.datetime.now(core.UTC)
        for fraction,weight,expected in [(0.015,1.25,30),(0.005,1.25,12.5),(0,1.25,0)]:
            with self.subTest(fraction=fraction):
                state=core.blank_state();wallet='A'*32
                state['observed'][wallet]={'count':10}
                ev=dict(wallet=wallet,token='pool',id='new',pool_name='sample',timestamp=now)
                with patch.object(core,'wallet_risk_fraction',return_value=fraction), patch.object(adaptive,'feature_risk_multiplier',return_value=(weight,'test')):
                    core.maybe_open(state,ev,1,now,{'pool':1})
                self.assertLessEqual(len(state['positions']),1)
                self.assertEqual(sum(p['notional_gbp'] for p in state['positions']),expected)
                self.assertTrue(state['paper_only'])

    def test_duplicate_outcomes_cannot_reinforce_feature_cohort(self):
        state=core.blank_state();r=adaptive.ensure(state)
        sample=dict(liquidity_usd=400000,change_24h_pct=12,signal_age_seconds=10)
        r['entry_features']={'same-signal':sample}
        state['closed']=[dict(wallet='W'+str(i%12),token='T'+str(i%6),signal_id='same-signal',
            net_pnl_gbp=1,roi_pct=10,exit_at=(dt.datetime.now(core.UTC)-dt.timedelta(days=i)).isoformat()) for i in range(42)]
        self.assertEqual(adaptive.feature_reports(state)['liq:250k+']['status'],'COLLECTING_EVIDENCE')
