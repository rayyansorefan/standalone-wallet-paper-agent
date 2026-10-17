"""No-key, free-data resilience without fabricated swaps or expanded risk."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import core
from agent.market_resilience import fetch_pairs

A='A'*32
B='B'*32
C='C'*32
D='D'*32
E='E'*32
MINT='G'*32


def pair(address,price='1.25',chain='solana',base=MINT):
    return {'pairAddress':address,'chainId':chain,'priceUsd':price,
            'baseToken':{'address':base},'quoteToken':{'address':'H'*32}}


def pool(address):
    now=dt.datetime.now(core.UTC)
    return {'id':'solana_'+address,
        'relationships':{'base_token':{'data':{'id':'solana_'+MINT}}},
        'attributes':{'address':address,'name':'TEST/SOL','reserve_in_usd':'300000',
          'volume_usd':{'h24':'500000'},'base_token_price_usd':'1.00',
          'pool_created_at':(now-dt.timedelta(days=8)).isoformat()}}


class FreePairQuotes(unittest.TestCase):
    def test_exact_pairs_only_even_if_provider_contains_wrong_chain(self):
        result=fetch_pairs([A,B],transport=lambda _: {'pairs':[
            pair(A),pair(C),pair(B,chain='ethereum'),pair(A,'999'),
            pair(B,'1.50')]})
        self.assertEqual(result,{A:1.25,B:1.5})

    def test_no_synthetic_prices_bad_payload_and_invalid_address(self):
        self.assertEqual(fetch_pairs([A],transport=lambda _: {'pairs':[]}),{})
        self.assertEqual(fetch_pairs([A],transport=lambda _: {'pairs':[
            pair(A,'NaN'),pair(A,'-1'),pair(A,base='bad')]}),{})
        with self.assertRaises(ValueError):
            fetch_pairs(['abc'],transport=lambda _: {'pairs':[]})
        with self.assertRaises(ValueError):
            fetch_pairs([A],transport=lambda _: {'error':'provider down'})

    def test_single_batched_public_url_without_token_keys(self):
        calls=[]
        def transport(url):
            calls.append(url)
            return {'pairs':[pair(A),pair(B)]}
        self.assertEqual(len(fetch_pairs([A,B,A],transport=transport)),2)
        self.assertEqual(len(calls),1)
        self.assertIn(A+','+B,calls[0])
        self.assertNotIn('api-key',calls[0].lower())


class LiveModeIntegration(unittest.TestCase):
    def run_prod(self,path,backend,screen=True):
        def mockapi(endpoint,params=None):
            return backend(endpoint,params)
        with (mock.patch.object(core,'api',side_effect=mockapi) as provider,
              mock.patch('agent.news.refresh'),
              mock.patch('agent.strategies.run'),
              mock.patch('agent.whales.whale_cycle') as whale):
            out=core.run_cycle(fetch=provider,path=path,screen_token=lambda _:screen)
            return out,provider,whale

    def test_rotating_two_main_trades_from_four_risk_approved_pools(self):
        def backend(endpoint,params):
            if 'trending_pools' in endpoint:return {'data':[pool(A),pool(B),pool(C),pool(D)]}
            if endpoint.endswith('/trades'):return {'data':[]}
            raise AssertionError('Unexpected Gecko detail request '+endpoint)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json'
            first,reqs,whale=self.run_prod(path,backend)
            first_trades=[c.args[0] for c in reqs.call_args_list if c.args[0].endswith('/trades')]
            self.assertEqual(len(first_trades),2)
            self.assertEqual(first['cycle_health']['trade_feeds_budget_deferred'],2)
            self.assertEqual(first['cycle_health']['trade_feeds_attempted'],2)
            self.assertEqual(first['last_status'],'BOOTSTRAPPED_NO_TRADES')
            second,reqs,whale=self.run_prod(path,backend)
            second_trades=[c.args[0] for c in reqs.call_args_list if c.args[0].endswith('/trades')]
            self.assertEqual(len(second_trades),2)
            self.assertFalse(set(first_trades)&set(second_trades))
            self.assertEqual(second['last_status'],'OK')
            self.assertEqual(second['completed_cycles'],2)

    def test_degraded_main_feed_defers_supplemental_whale_requests(self):
        def backend(endpoint,params):
            raise RuntimeError('GeckoTerminal public provider 429')
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json'
            state=core.blank_state()
            state['last_run']=(dt.datetime.now(core.UTC)-dt.timedelta(minutes=5)).isoformat()
            core.save(state,path)
            out,api,whale=self.run_prod(path,backend)
            whale.assert_not_called()
            self.assertEqual(out['last_status'],'API_ERROR')
            self.assertEqual(out['research']['whale_v3']['status'],'DEFERRED_PRIMARY_PRIORITY')
            self.assertEqual(out['cash_gbp'],2000)
            self.assertEqual(out['positions'],[])
            self.assertEqual(out['completed_cycles'],1)

    def test_held_position_is_marked_by_free_quote_without_gecko_pool_call(self):
        def backend(endpoint,params):
            if 'trending_pools' in endpoint:return {'data':[]}
            raise AssertionError('Existing quote must not require Gecko pool request')
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json'
            state=core.blank_state()
            state['last_run']=(dt.datetime.now(core.UTC)-dt.timedelta(minutes=5)).isoformat()
            state['cash_gbp']=1989.9
            state['positions']=[{'wallet':'wallet','token':E,'pool_name':'TEST',
                       'opened_at':(dt.datetime.now(core.UTC)-dt.timedelta(minutes=15)).isoformat(),
                       'entry_price_usd':1,'notional_gbp':10,'cost_gbp':10.1}]
            core.save(state,path)
            with mock.patch('agent.market_resilience.fetch_pairs',return_value={E:1.10}) as alt:
                out,api,whale=self.run_prod(path,backend)
            alt.assert_called_once_with([E])
            self.assertEqual(out['research']['alternate_price_feed_v1']['status'],'OK')
            self.assertEqual(out['positions'][0]['last_mark_price_usd'],1.1)
            self.assertEqual(out['positions'][0]['token'],E)
            self.assertEqual(len(out['closed']),0)
            self.assertEqual(out['cash_gbp'],1989.9)
            self.assertTrue(all('/pools/'+E not in c.args[0] for c in api.call_args_list))


if __name__=='__main__': unittest.main()
