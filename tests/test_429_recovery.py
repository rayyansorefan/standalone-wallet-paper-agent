"""Protect wide free discovery and five-minute paper trading from repeat HTTP429s."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from agent import core

UTC=dt.timezone.utc
NOW=dt.datetime(2026,10,17,21,tzinfo=UTC)
A='A'*32
M='G'*32


def pool(address=A):
    return {'id':'solana_'+address,
            'relationships':{'base_token':{'data':{'id':'solana_'+M}}},
            'attributes':{'address':address,'name':'TEST/SOL',
                'reserve_in_usd':'300000','volume_usd':{'h24':'500000'},
                'base_token_price_usd':'1',
                'pool_created_at':(dt.datetime.now(UTC)-dt.timedelta(days=5)).isoformat()}}


class Provider429Recovery(unittest.TestCase):
    def test_recent_rate_limit_uses_2_then_3_then_4_never_six_after_one_hour(self):
        at=NOW-dt.timedelta(minutes=10)
        for mins,expected in [(10,2),(31,3),(61,4),(300,4),
                              (1440,6)]:
            now=at+dt.timedelta(minutes=mins)
            health={'last_rate_limit_at':at.isoformat(),
                    'healthy_sampling_cycles':288}
            self.assertEqual(core.swap_budget(health,now),expected)
        self.assertEqual(core.swap_budget({'healthy_sampling_cycles':12},NOW),4)
        self.assertEqual(core.swap_budget({'healthy_sampling_cycles':287},NOW),4)
        self.assertEqual(core.swap_budget({'healthy_sampling_cycles':288},NOW),6)

    def test_rate_limited_core_does_not_repeatedly_call_closed_circuit(self):
        calls=[]
        def backend(endpoint,params=None):
            calls.append(endpoint)
            if 'trending_pools' in endpoint:
                return {'data':[pool(A),pool('B'*32),pool('C'*32)]}
            if endpoint.endswith('/trades'):
                self.fail('Never call Gecko swaps while a retry-after is active')
            raise AssertionError(endpoint)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json'
            state=core.blank_state()
            state['last_run']=(dt.datetime.now(UTC)-dt.timedelta(minutes=5)).isoformat()
            state['research']={'primary_provider_v1':{
                'retry_at':(dt.datetime.now(UTC)+dt.timedelta(minutes=3)).isoformat(),
                'last_rate_limit_at':(dt.datetime.now(UTC)-dt.timedelta(minutes=2)).isoformat(),
                'http_status':429}}
            core.save(state,path)
            with (mock.patch.object(core,'api',side_effect=backend) as provider,
                  mock.patch('agent.opportunity_discovery.discover',return_value=([],{})),
                  mock.patch('agent.news.refresh'),
                  mock.patch('agent.strategies.run'),
                  mock.patch('agent.whales.whale_cycle')):
                provider.__name__='api'
                latest=core.run_cycle(fetch=provider,path=path,screen_token=lambda _:True)
            h=latest['cycle_health']
            self.assertEqual(h['trade_feeds_attempted'],0)
            self.assertEqual(h['trade_feeds_provider_cooldown_deferred'],3)
            self.assertEqual(h['trade_feeds_sampled'],0)
            self.assertEqual(sum(x.endswith('/trades') for x in calls),0)
            self.assertEqual(len(latest['closed']),0)
            self.assertEqual(len(latest['positions']),0)
            self.assertTrue(latest['paper_only'])
            self.assertEqual(latest['cash_gbp'],2000)
            self.assertEqual(core.load(path),latest)

    def test_extra_gecko_discovery_is_skipped_during_recent_rate_limit(self):
        now=dt.datetime.now(UTC)
        seen=[]
        def backend(endpoint,params=None):
            seen.append((endpoint,params))
            if 'trending_pools' in endpoint:return {'data':[pool(A)]}
            if endpoint.endswith('/trades'):return {'data':[]}
            raise AssertionError(endpoint)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json'
            state=core.blank_state()
            state['last_run']=(now-dt.timedelta(minutes=5)).isoformat()
            state['research']={'primary_provider_v1':{
                'last_rate_limit_at':(now-dt.timedelta(minutes=32)).isoformat(),
                'healthy_sampling_cycles':0}}
            core.save(state,path)
            with (mock.patch.object(core,'api',side_effect=backend) as provider,
                  mock.patch('agent.opportunity_discovery.discover',return_value=([],{})),
                  mock.patch('agent.news.refresh'),
                  mock.patch('agent.strategies.run'),
                  mock.patch('agent.whales.whale_cycle')):
                provider.__name__='api'
                x=core.run_cycle(fetch=provider,path=path,screen_token=lambda _:True)
            self.assertEqual(len([e for e,p in seen if 'trending_pools' in e]),1)
            self.assertEqual(x['cycle_health']['trade_feed_budget'],3)
            self.assertTrue(x['research']['broad_discovery_v1']['gecko_extra_page_deferred'])

    def test_page_cursor_cycles_without_permanently_starving_pages(self):
        seen=[]
        def backend(endpoint,params=None):
            if 'trending_pools' in endpoint:
                seen.append(params['page'])
                return {'data':[pool()]}
            if endpoint.endswith('/trades'):return {'data':[]}
            raise AssertionError(endpoint)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json'
            state=core.blank_state()
            state['last_run']=(dt.datetime.now(UTC)-dt.timedelta(minutes=5)).isoformat()
            core.save(state,path)
            with (mock.patch.object(core,'api',side_effect=backend) as provider,
                  mock.patch('agent.opportunity_discovery.discover',return_value=([],{})),
                  mock.patch('agent.news.refresh'),
                  mock.patch('agent.strategies.run'),
                  mock.patch('agent.whales.whale_cycle')):
                provider.__name__='api'
                for _ in range(12): core.run_cycle(fetch=provider,path=path,screen_token=lambda _:True)
            extra=[p for p in seen if p!=1]
            self.assertEqual(extra,[2,3,4,5])

if __name__=='__main__':unittest.main()
