"""Regression of run 39043761627: Rugcheck 400 on one mint, others safe.

Never allow a trade on an unverified token; don't erase the health of the
other independently screened pools, and don't conceal genuine feed failures.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from agent import core

UTC=core.UTC
ADDRESSES=['B'*32,'C'*32,'D'*32,'E'*32]
MINTS=['A'*32,'F'*32,'G'*32,'H'*32]


def pool(address,mint):
    return {'id':'solana_'+address,
            'relationships':{'base_token':{'data':{'id':'solana_'+mint}}},
            'attributes':{'address':address,'name':'TEST / SOL',
                          'reserve_in_usd':'500000',
                          'volume_usd':{'h24':'600000'},
                          'base_token_price_usd':'1',
                          'pool_created_at':(dt.datetime.now(UTC)-dt.timedelta(days=4)).isoformat()}}


def feed(path,params=None):
    if path.endswith('/trades'):
        return {'data':[]}
    return {'data':[pool(p,m) for p,m in zip(ADDRESSES,MINTS)]}


def screener(mint):
    if mint==MINTS[2]:
        return {'status':'UNAVAILABLE','allowed':False,'reason':'security API HTTP error','http_status':400}
    return {'status':'PASS','allowed':True,'reason':'risk score and flags pass provisional screen',
            'score_normalised':1}


class ScreeningIsolation(unittest.TestCase):
    def test_one_http400_other_three_pass_feeds_fetched_and_positions_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=core.run_cycle(fetch=feed,path=Path(tmp)/'state.json',screen_token=screener)
            self.assertEqual(state['last_status'],'PARTIAL_SCREENING_UNAVAILABLE')
            self.assertEqual(state['cycle_health']['screened_pass'],3)
            self.assertEqual(state['cycle_health']['screened_unavailable'],1)
            self.assertEqual(state['cycle_health']['trade_feeds_sampled'],3)
            self.assertEqual(state['cycle_health']['screening_http_statuses'],[400])
            self.assertEqual(state['cycle_health']['errors_this_cycle'],1)
            self.assertEqual(state['positions'],[])
            self.assertTrue(all(s['status']=='PASS' for s in state['screening'][:2]))
            self.assertEqual(state['screening'][2]['status'],'UNAVAILABLE')
            self.assertTrue(Path(tmp,'state.json').is_file())

    def test_next_good_cycle_clears_current_errors_without_erasing_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'
            bad=core.run_cycle(fetch=feed,path=path,screen_token=screener)
            self.assertEqual(bad['last_status'],'PARTIAL_SCREENING_UNAVAILABLE')
            good=core.run_cycle(fetch=feed,path=path,screen_token=lambda mint:{
                'status':'PASS','allowed':True,'reason':'low risk','score_normalised':1})
            self.assertEqual(good['last_status'],'OK')
            self.assertEqual(good['cycle_health']['errors_this_cycle'],0)
            self.assertEqual(good['cycle_health']['screened_unavailable'],0)
            self.assertEqual(good['cycle_health']['screened_pass'],4)
            self.assertEqual(len(good['errors']),1)
            self.assertEqual(good['completed_cycles'],2)

    def test_all_security_checks_unavailable_remains_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad=core.run_cycle(fetch=feed,path=Path(tmp)/'state.json',screen_token=lambda mint:{
                'status':'UNAVAILABLE','allowed':False,'reason':'security API HTTP error',
                'http_status':400})
            self.assertEqual(bad['last_status'],'SCREENING_UNAVAILABLE')
            self.assertFalse(bad['cycle_health']['partial_screening_only'])
            self.assertEqual(bad['cycle_health']['trade_feeds_sampled'],0)
            self.assertEqual(bad['positions'],[])

    def test_additional_trade_provider_failure_remains_degraded(self):
        def failing_feed(path,params=None):
            if path.endswith('/trades'):raise OSError('mock trade feed outage')
            return feed(path,params)
        with tempfile.TemporaryDirectory() as tmp:
            x=core.run_cycle(fetch=failing_feed,path=Path(tmp)/'state.json',screen_token=screener)
            self.assertNotEqual(x['last_status'],'PARTIAL_SCREENING_UNAVAILABLE')
            self.assertEqual(x['last_status'],'TRADE_FEEDS_FAILED')
            self.assertGreater(x['cycle_health']['errors_this_cycle'],1)
            self.assertEqual(x['positions'],[])

if __name__=='__main__':unittest.main()
