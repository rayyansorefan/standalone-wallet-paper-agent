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

if __name__=='__main__':unittest.main()
