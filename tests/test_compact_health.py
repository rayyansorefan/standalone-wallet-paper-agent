"""Tiny per-cycle health report works even when full state is too large to fetch."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import core, dashboard, scheduled


class CompactHealth(unittest.TestCase):
    def test_minimal_health_report_is_readable_and_has_no_history_or_wallets(self):
        s=core.blank_state()
        s['paper_only']=True
        s['last_run']='2026-10-17T15:19:05+00:00'
        s['last_status']='DEGRADED'
        s['completed_cycles']=480
        s['positions']=[{'wallet':'private-wallet','token':'private-token'}]
        s['closed']=[{'wallet':'closed-wallet'}]
        s['cycle_health']={'errors_this_cycle':2,
                           'error_messages':['risk API HTTP 429','trade provider timeout']}
        s['research']={'primary_provider_v1':{'http_status':429,'rate_limit_strikes':2,
                                              'retry_at':'2026-10-17T15:29:05+00:00'},
                       'strategies_v1':{'status':'COLLECTING_FORWARD_EVIDENCE',
                                        'closed':[{'private':'details'}],
                                        'summary':{'wins':0}}}
        original=json.dumps(s,sort_keys=True)
        report=dashboard.compact_health(s)
        with tempfile.TemporaryDirectory() as d:
            dst=Path(d)/'health.json'
            dashboard.publish_health(s,dst)
            body=dst.read_text()
            parsed=json.loads(body)
        self.assertEqual(parsed,report)
        self.assertEqual(parsed['status'],'DEGRADED')
        self.assertEqual(parsed['cycle_health']['errors_this_cycle'],2)
        self.assertEqual(parsed['primary_provider']['rate_limit_strikes'],2)
        self.assertEqual(parsed['futures']['closed'],1)
        self.assertEqual(parsed['original']['open_positions'],1)
        for secret in ('private-wallet','private-token','closed-wallet'):
            self.assertNotIn(secret,body)
        self.assertLess(len(body),8000)
        self.assertEqual(json.dumps(s,sort_keys=True),original)

    def test_realised_profit_and_six_hour_loss_trend_are_available_without_full_ledger(self):
        s=core.blank_state()
        s['last_run']='2026-10-17T22:00:00+00:00'
        s['cash_gbp']=1980.35
        s['positions']=[{'wallet':'private-wallet','notional_gbp':10.0}]
        s['closed']=[
            {'wallet':'secret1','net_pnl_gbp':3.0,
             'exit_at':'2026-10-16T00:00:00+00:00'},
            {'wallet':'secret2','net_pnl_gbp':-.60,
             'exit_at':'2026-10-17T20:00:00+00:00'},
            {'wallet':'secret3','net_pnl_gbp':-.40,
             'exit_at':'2026-10-17T21:30:00+00:00'},
            {'wallet':'secret4','net_pnl_gbp':1.20,
             'exit_at':'2026-10-17T21:55:00+00:00'}]
        pristine=json.dumps(s,sort_keys=True)
        health=dashboard.compact_health(s)
        p=health['original']['performance']
        self.assertEqual(p['starting_gbp'],2000)
        self.assertEqual(p['available_cash_gbp'],1980.35)
        self.assertEqual(p['open_notional_gbp'],10.)
        self.assertEqual(p['all_time']['closed'],4)
        self.assertEqual(p['all_time']['wins'],2)
        self.assertEqual(p['all_time']['losses'],2)
        self.assertEqual(p['all_time']['win_rate_pct'],50)
        self.assertEqual(p['all_time']['net_pnl_gbp'],3.2)
        self.assertEqual(p['last_6h']['closed'],3)
        self.assertEqual(p['last_6h']['losses'],2)
        self.assertEqual(p['last_6h']['net_pnl_gbp'],.2)
        self.assertEqual(p['last_24h']['net_pnl_gbp'],.2)
        self.assertIn('CLOSED GBP paper only',p['method'])
        for secret in ('secret1','secret2','secret3','secret4','private-wallet'):
            self.assertNotIn(secret,json.dumps(health))
        self.assertEqual(json.dumps(s,sort_keys=True),pristine)

    def test_missing_pnl_or_unknown_timestamp_is_not_falsely_profitable(self):
        s=core.blank_state()
        s['last_run']='2026-10-17T22:00:00+00:00'
        s['closed']=[{'exit_at':'2026-10-17T21:45:00+00:00',
                      'net_pnl_gbp':2},
                     {'exit_at':'2026-10-17T21:55:00+00:00'}]
        p=dashboard.compact_health(s)['original']['performance']
        self.assertFalse(p['all_time']['complete_outcomes'])
        self.assertIsNone(p['all_time']['net_pnl_gbp'])
        self.assertFalse(p['last_6h']['complete_outcomes'])
        self.assertIsNone(p['last_6h']['win_rate_pct'])
        s['last_run']=None
        p=dashboard.compact_health(s)['original']['performance']
        self.assertFalse(p['last_6h']['data_available'])
        self.assertIsNone(p['last_24h']['closed'])

    def test_invalidated_forward_epoch_is_published_without_private_books(self):
        s=core.blank_state()
        s['research']['forward_experiment_epochs_v1']=[{
            'version':'paired-pullback-1',
            'registered_at':'2026-10-18T07:44:16+00:00',
            'invalidated_at':'2026-10-18T08:28:46+00:00',
            'archived_at':'2026-10-18T12:30:00+00:00',
            'invalid_reason':'ECONOMIC_SOURCE_CHANGED_NO_AUTOMATIC_RESTART',
            'archive_reason':'FROZEN_SOURCE_INVALIDATED',
            'source_sha256':'frozen-hash',
            'arms':{'baseline':{'private':'do-not-publish'}},
            'summary':{'status':'INVALIDATED',
                       'arms':{'baseline':{'closed':1,'net_usd':-4.81776}}}
        }]
        body=json.dumps(dashboard.compact_health(s))
        archive=json.loads(body)['forward_experiment_archive']
        self.assertEqual(len(archive),1)
        self.assertEqual(archive[0]['version'],'paired-pullback-1')
        self.assertEqual(archive[0]['summary']['arms']['baseline']['closed'],1)
        self.assertNotIn('do-not-publish',body)

    def test_healthy_cycle_does_not_resurface_old_errors(self):
        s=core.blank_state()
        s.update(last_status='OK',errors=[{'at':'yesterday','error':'old 429'}])
        self.assertEqual(dashboard.compact_health(s)['recent_errors'],[])
        self.assertEqual(dashboard.compact_health(s)['status'],'OK')

    def test_scheduled_cycle_persists_tiny_diagnostic_alongside_account(self):
        now=dt.datetime(2026,10,17,15,25,tzinfo=core.UTC)
        s=core.blank_state()
        s['last_run']=(now-dt.timedelta(minutes=5)).isoformat()
        s['cash_gbp']=1980
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'state.json'
            feed=Path(root)/'state-public.json'
            core.save(s,path)
            def runner(path):
                state=core.load(path)
                state['last_run']=now.isoformat()
                state['last_status']='DEGRADED'
                state['completed_cycles']+=1
                state['cycle_health']={'error_messages':['provider timeout'],
                                       'errors_this_cycle':1}
                return state
            with mock.patch.dict('os.environ',{'GITHUB_RUN_ID':'777','PAPER_SCHEDULER':'google-apps-script'}):
                self.assertTrue(scheduled.execute(path,feed,now,runner))
            health=json.loads((Path(root)/'health.json').read_text())
            self.assertEqual(health['status'],'DEGRADED')
            self.assertEqual(health['execution']['run_id'],'777')
            self.assertEqual(health['execution']['scheduler'],'google-apps-script')
            self.assertEqual(core.load(path)['cash_gbp'],1980)
            self.assertEqual(json.loads(feed.read_text())['last_status'],'DEGRADED')

    def test_missing_health_fields_do_not_make_an_unhealthy_cycle_look_ok(self):
        s={'paper_only':True,'last_status':'SCREENING_UNAVAILABLE'}
        h=dashboard.compact_health(s)
        self.assertEqual(h['status'],'SCREENING_UNAVAILABLE')
        self.assertIsNone(h['primary_provider']['retry_at'])
        self.assertEqual(h['cycle'],None)


    def test_position_management_health_is_account_safe_and_evidence_based(self):
        state=core.blank_state()
        state['positions']=[
            {'wallet':'private-wallet','token':'secret-token',
             'last_mark_at':'2026-10-17T16:55:00+00:00',
             'trailing_stop_price_usd':1.18,
             'additions':[{'notional_gbp':4.0}], 'position_action':'LOSS_WARNING',
             'loss_warning_active':True},
            {'wallet':'other-secret','token':'other-pool',
             'position_action':'UNPRICED_HOLD'}]
        state['closed']=[{'wallet':'old-secret',
                         'additions':[{'notional_gbp':3.0}]}]
        state['decisions']=[{'action':'PAPER_ADD_WINNER','at':'2026-10-17T16:50:00+00:00',
                             'wallet':'private-wallet','token':'secret-token'}]
        health=dashboard.compact_health(state)
        stats=health['position_management']
        self.assertEqual(stats['open_with_additions'],1)
        self.assertEqual(stats['closed_with_additions'],1)
        self.assertEqual(stats['open_additions'],1)
        self.assertEqual(stats['closed_additions'],1)
        self.assertEqual(stats['open_with_trailing_protection'],1)
        self.assertEqual(stats['open_with_recorded_mark'],1)
        self.assertEqual(stats['open_unpriced'],1)
        self.assertEqual(stats['open_loss_warnings'],1)
        self.assertEqual(stats['closed_at_4_5pct_stop'],0)
        self.assertEqual(stats['net_loss_warning_pct'],-2.0)
        self.assertEqual(stats['net_loss_exit_pct'],-4.5)
        self.assertEqual(stats['last_add_at'],'2026-10-17T16:50:00+00:00')
        published=json.dumps(health)
        for secret in ('private-wallet','secret-token','other-secret','old-secret'):
            self.assertNotIn(secret,published)

if __name__=='__main__':unittest.main()
