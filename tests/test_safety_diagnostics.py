import datetime as dt
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock
from agent import core
from agent.safety import inspect_token

MINT = 'A'*32
POOL = 'B'*32

class Diagnostics(unittest.TestCase):
    def test_production_security_outage_opens_fail_closed_backoff_and_recovers(self):
        now=dt.datetime.now(core.UTC)
        chars='ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        pools=[]
        for i in range(12):
            pools.append(dict(pool=chars[i]*32,mint=chars[i+12]*32,
                name='TEST/SOL',liquidity_usd=300000.,volume_24h_usd=450000.,
                price_usd=1.25,age_hours=120.,change_24h_pct=1.,
                change_1h_pct=1.,change_5m_pct=0.,volume_1h_usd=30000.,
                buys_1h=80.,sells_1h=60.))
        report={'raw_token_mints':12,'qualified_pairs':12,
                'eligible_unique_pools':12,'raw_pool_rows':12,
                'prior_mints_requested':0,'prior_mints_refreshed':0,
                'search_requests':4,'search_rows_examined':120,
                'search_queries':['A','B','C','D'],'errors':[]}
        def backend(endpoint,params=None):
            if endpoint.endswith('/trending_pools'):return {'data':[]}
            if endpoint.endswith('/trades'):return {'data':[]}
            raise AssertionError(endpoint)
        calls=[]
        unavailable=lambda mint:(calls.append(mint) or {
            'status':'UNAVAILABLE','allowed':False,
            'reason':'security API request or JSON failed'})
        passing=lambda mint:(calls.append(mint) or {
            'status':'PASS','allowed':True,'reason':'available'})
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'s.json'
            state=core.blank_state()
            state['last_run']=(now-dt.timedelta(minutes=5)).isoformat()
            core.save(state,path)
            with (mock.patch.object(core,'api',side_effect=backend) as provider,
                  mock.patch('agent.opportunity_discovery.discover',
                             return_value=(pools,report)),
                  mock.patch('agent.news.refresh'),
                  mock.patch('agent.strategies.run'),
                  mock.patch('agent.whales.whale_cycle')):
                provider.__name__='api'
                failed=core.run_cycle(fetch=provider,path=path,
                                      screen_token=unavailable)
                self.assertEqual(len(calls),1)
                self.assertEqual(failed['last_status'],'SCREENING_UNAVAILABLE')
                health=failed['cycle_health']
                self.assertEqual(health['security_screened'],1)
                self.assertEqual(health['security_screening_slots_considered'],10)
                self.assertEqual(health['security_provider_backoff_deferred'],9)
                self.assertTrue(health['security_provider_backoff_active'])
                self.assertEqual(failed['positions'],[])
                self.assertEqual(failed['cash_gbp'],2000)

                backed_off=core.run_cycle(fetch=provider,path=path,
                                          screen_token=passing)
                self.assertEqual(len(calls),1)  # no calls before retry time
                self.assertEqual(backed_off['cycle_health']['security_screened'],0)
                self.assertEqual(
                    backed_off['cycle_health']['security_provider_backoff_deferred'],10)
                self.assertEqual(backed_off['positions'],[])

                saved=core.load(path)
                saved['research']['security_provider_v1']['retry_at']=(
                    now-dt.timedelta(seconds=1)).isoformat()
                core.save(saved,path)
                recovered=core.run_cycle(fetch=provider,path=path,
                                         screen_token=passing)
                self.assertEqual(len(calls),11)
                self.assertEqual(recovered['cycle_health']['security_screened'],10)
                self.assertEqual(
                    recovered['cycle_health']['security_provider_backoff_deferred'],0)
                self.assertFalse(
                    recovered['cycle_health']['security_provider_backoff_active'])
                self.assertIsNone(recovered['research']['security_provider_v1']['retry_at'])
                self.assertEqual(recovered['cash_gbp'],2000)

    def test_low_risk_valid_report_passes(self):
        x=inspect_token(MINT,fetch=lambda _: {'score_normalised':12,'risks':[{'name':'Mutable metadata','level':'warn'}]})
        self.assertEqual(x['status'],'PASS')
        self.assertTrue(x['allowed'])

    def test_high_score_rejected_but_not_provider_failure(self):
        x=inspect_token(MINT,fetch=lambda _: {'score_normalised':75,'risks':[]})
        self.assertEqual(x['status'],'REJECTED')
        self.assertFalse(x['allowed'])
        self.assertIn('25',x['reason'])

    def test_high_severity_rejected_even_below_score_threshold(self):
        x=inspect_token(MINT,fetch=lambda _: {'score_normalised':9,'risks':[{'level':'danger','name':'Insider cluster'}]})
        self.assertEqual(x['status'],'REJECTED')

    def test_missing_risk_evidence_fails_closed(self):
        self.assertEqual(inspect_token(MINT,fetch=lambda _: {'score_normalised':5})['status'],'UNAVAILABLE')
        self.assertEqual(inspect_token(MINT,fetch=lambda _: {'risks':[]})['status'],'UNAVAILABLE')
        self.assertEqual(inspect_token(MINT,fetch=lambda _: {'score_normalised':float('nan'),'risks':[]})['status'],'UNAVAILABLE')

    def test_http_429_is_unavailable(self):
        def fail(_):
            raise urllib.error.HTTPError('https://api.rugcheck.xyz',429,'Too Many Requests',{},None)
        x=inspect_token(MINT,fetch=fail)
        self.assertEqual(x['status'],'UNAVAILABLE')
        self.assertEqual(x['http_status'],429)
        self.assertFalse(x['allowed'])

    def test_all_risky_pools_create_healthy_no_safe_pools_status(self):
        stamp=dt.datetime.now(core.UTC)
        pool={'id':'solana_'+POOL,
              'relationships':{'base_token':{'data':{'id':'solana_'+MINT}}},
              'attributes':{'address':POOL,'name':'RISKY / SOL',
                  'reserve_in_usd':'250000', 'volume_usd':{'h24':'300000'},
                  'base_token_price_usd':'1',
                  'pool_created_at':(stamp-dt.timedelta(days=4)).isoformat()}}
        def fetch(path,params=None): return {'data':[pool]}
        with tempfile.TemporaryDirectory() as root:
            state=core.run_cycle(fetch=fetch,path=Path(root)/'s.json',
                screen_token=lambda _: {'status':'REJECTED','allowed':False,
                  'reason':'score above threshold','score_normalised':45})
            self.assertEqual(state['last_status'],'NO_SAFE_POOLS')
            self.assertEqual(state['positions'],[])
            self.assertEqual(state['screening'][0]['score_normalised'],45)
            self.assertEqual(state['errors'],[])
        with tempfile.TemporaryDirectory() as root:
            state=core.run_cycle(fetch=fetch,path=Path(root)/'s.json',
                screen_token=lambda _: {'status':'UNAVAILABLE','allowed':False,
                  'reason':'security API HTTP error','http_status':429})
            self.assertEqual(state['last_status'],'SCREENING_UNAVAILABLE')
            self.assertEqual(state['positions'],[])
            self.assertEqual(state['screening'][0]['http_status'],429)
            self.assertTrue(state['errors'])

if __name__=='__main__': unittest.main()
