import datetime as dt
import tempfile
import unittest
import urllib.error
from pathlib import Path
from agent import core
from agent.safety import inspect_token

MINT = 'A'*32
POOL = 'B'*32

class Diagnostics(unittest.TestCase):
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
