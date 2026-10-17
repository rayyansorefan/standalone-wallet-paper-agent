"""Secure, bounded Helius free-tier RPC readiness tests; no real API calls."""
import datetime as dt
import json
import unittest
from unittest import mock

from agent.helius_rpc import standard_rpc, probe

NOW=dt.datetime(2026,10,17,16,tzinfo=dt.timezone.utc)
ADDRESS='A'*32
FAKE_KEY='TEST_KEY_SHOULD_NEVER_APPEAR_IN_SAVED_STATE'


class HeliusReadiness(unittest.TestCase):
    def test_standard_rpc_reads_confirmed_signatures_only(self):
        calls=[]
        def transport(url,raw):
            calls.append((url,json.loads(raw)))
            return {'jsonrpc':'2.0','result':[{'signature':'sig-one'},{'signature':'sig-two'}]}
        count=standard_rpc(FAKE_KEY,ADDRESS,transport=transport)
        self.assertEqual(count,2)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1]['method'],'getSignaturesForAddress')
        self.assertEqual(calls[0][1]['params'][0],ADDRESS)
        self.assertEqual(calls[0][1]['params'][1]['limit'],5)
        self.assertNotIn(FAKE_KEY,json.dumps(calls[0][1]))

    def test_probe_missing_secret_avoids_network_and_is_unconfigured(self):
        state={'cash_gbp':1990,'positions':[{'token':'existing'}]}
        with mock.patch.dict('os.environ',{'HELIUS_API_KEY':''}):
            health=probe(state,[{'pool':ADDRESS}],now=NOW,
                         rpc=lambda *a: self.fail('Never call RPC when unconfigured'))
        self.assertEqual(health['status'],'NOT_CONFIGURED')
        self.assertEqual(state['cash_gbp'],1990)
        self.assertEqual(len(state['positions']),1)

    def test_probe_success_is_throttled_and_records_no_signatures_or_key(self):
        state={'research':{},'paper_only':True,'closed':[{'old':1}]}
        calls=[]
        def rpc(key,address):
            calls.append((key,address))
            return 5
        report=probe(state,[{'pool':ADDRESS}],now=NOW,key=FAKE_KEY,rpc=rpc)
        self.assertEqual(report['status'],'AVAILABLE')
        self.assertEqual(report['sampled_signatures'],5)
        probe(state,[{'pool':ADDRESS}],now=NOW+dt.timedelta(minutes=10),key=FAKE_KEY,rpc=rpc)
        self.assertEqual(len(calls),1)
        probe(state,[{'pool':ADDRESS}],now=NOW+dt.timedelta(minutes=31),key=FAKE_KEY,rpc=rpc)
        self.assertEqual(len(calls),2)
        self.assertEqual(state['closed'],[{'old':1}])
        self.assertNotIn(FAKE_KEY,json.dumps(state))
        self.assertNotIn('sig-one',json.dumps(state))
        self.assertFalse(report['swap_decoding'])

    def test_probe_exception_must_not_leak_url_or_key(self):
        state={'research':{}}
        def leak(*_):
            raise RuntimeError('https://mainnet.helius-rpc.com/?api-key='+FAKE_KEY)
        result=probe(state,[{'pool':ADDRESS}],now=NOW,key=FAKE_KEY,rpc=leak)
        self.assertEqual(result['status'],'UNAVAILABLE')
        self.assertEqual(result['error_type'],'RuntimeError')
        self.assertNotIn(FAKE_KEY,json.dumps(state))
        self.assertNotIn('https://',json.dumps(state))

    def test_unusable_or_invalid_rpc_response_rejected(self):
        for payload in ({'error':{'message':'unauthorized'}},
                        {'result':'not-an-array'},
                        {'result':[{'bad':'signature'}]},
                        {'result':[{'signature':'x'}]*6}):
            with self.assertRaises(ValueError):
                standard_rpc(FAKE_KEY,ADDRESS,transport=lambda *args:payload)
        with self.assertRaises(ValueError):
            standard_rpc(FAKE_KEY,'bad',transport=lambda *args:{})

    def test_no_candidate_is_silent_and_does_not_call_provider(self):
        state={}
        r=probe(state,[],now=NOW,key=FAKE_KEY,rpc=lambda *a:self.fail('unneeded RPC'))
        self.assertEqual(r['status'],'NO_ACCOUNT_TO_PROBE')

if __name__=='__main__':
    unittest.main()
