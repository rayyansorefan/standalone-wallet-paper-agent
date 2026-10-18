"""Broad FREE no-key discovery: independent pools, bounded requests, no trades."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from agent import core
from agent.opportunity_discovery import choose_pair,discover

NOW=dt.datetime(2026,10,17,19,tzinfo=dt.timezone.utc)
MINTS=[c*32 for c in 'ABCDEFGHJKLMNPQRSTUVWXYZ']
POOL_IDS=[c*32 for c in 'ABCDEFGHJKLMNPQRSTUVWXYZ']


def ds_pair(mint,pool_address,price='1.25'):
    return {'chainId':'solana','pairAddress':pool_address,
            'baseToken':{'address':mint,'symbol':'TEST'},'quoteToken':{'address':'J'*32},
            'priceUsd':price,'pairCreatedAt':int((NOW-dt.timedelta(days=5)).timestamp()*1000),
            'liquidity':{'usd':300_000},'volume':{'h1':30_000,'h24':450_000},
            'priceChange':{'m5':2.5,'h1':5.0,'h24':10.0},
            'txns':{'h1':{'buys':80,'sells':60}},
            'fdv':1_500_000,'marketCap':1_200_000}


def gecko_pool(address,mint):
    return {'id':'solana_'+address,
            'relationships':{'base_token':{'data':{'id':'solana_'+mint}}},
            'attributes':{'address':address,'name':'GEO/SOL',
              'reserve_in_usd':'300000','volume_usd':{'h24':'450000','h1':'30000'},
              'price_change_percentage':{'m5':'2.5','h1':'5','h24':'10'},
              'transactions':{'h1':{'buys':80,'sells':60}},
              'base_token_price_usd':'1.25',
              'pool_created_at':(dt.datetime.now(core.UTC)-dt.timedelta(days=5)).isoformat()}}


class BroadDiscovery(unittest.TestCase):
    def test_only_supported_fresh_valid_sol_pools_are_candidates(self):
        p=ds_pair(MINTS[0],POOL_IDS[0])
        item=choose_pair(p,NOW)
        self.assertEqual(item['pool'],POOL_IDS[0])
        self.assertEqual(item['mint'],MINTS[0])
        self.assertEqual(item['buys_1h'],80)
        self.assertEqual(item['change_5m_pct'],2.5)
        self.assertTrue(core.eligible(item))
        self.assertTrue(item['promotion_is_not_safety_approval'])
        for change in [
            {'chainId':'ethereum'},
            {'pairAddress':'garbage'},
            {'priceUsd':'NaN'},
            {'liquidity':{'usd':99_999}},
            {'volume':{'h24':100_000}},
            {'pairCreatedAt':int((NOW-dt.timedelta(hours=1)).timestamp()*1000)},
        ]:
            self.assertIsNone(choose_pair({**p,**change},NOW))

    def test_batched_provider_load_covers_independent_sources_in_four_requests(self):
        seen=[]
        mints=MINTS[:20]
        def get(path):
            seen.append(path)
            if 'token-profiles' in path:
                return [{'chainId':'solana','tokenAddress':m} for m in mints[:12]]
            if 'token-boosts' in path:
                return [{'chainId':'solana','tokenAddress':m} for m in mints[12:]]
            if '/latest/dex/search?' in path:
                return {'pairs':[]}
            if '/tokens/v1/solana/' in path:
                batch=path.rsplit('/',1)[1].split(',')
                return [ds_pair(m,POOL_IDS[mints.index(m)]) for m in batch]
            self.fail('Unexpected HTTP resource')
        rows,health=discover(get=get,now=NOW)
        self.assertEqual(len(rows),20)
        self.assertEqual(health['raw_token_mints'],20)
        self.assertEqual(health['qualified_pairs'],20)
        self.assertEqual(health['batch_requests'],1)
        self.assertEqual(len(seen),7)
        self.assertEqual(health['search_requests'],4)
        self.assertEqual(health['coverage_target'],100)
        self.assertTrue(all(core.eligible(t) for t in rows))

    def test_search_expands_100_mints_without_claiming_safety(self):
        alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        mints=[alphabet[i//58]+alphabet[i%58]*31 for i in range(100)]
        pools=[alphabet[(i+2)//58]+alphabet[(i+2)%58]*31 for i in range(100)]
        seen=[]
        def get(path):
            seen.append(path)
            if 'token-profiles' in path:
                return [{'chainId':'solana','tokenAddress':m} for m in mints[:10]]
            if 'token-boosts' in path:
                return [{'chainId':'solana','tokenAddress':m} for m in mints[10:20]]
            if '/latest/dex/search?' in path:
                q=path.split('=')[-1]
                index={'SOL':20,'USDC':40,'BONK':60,'AI':80}[q]
                return {'pairs':[ds_pair(mints[i],pools[i]) for i in range(index,index+20)]}
            if '/tokens/v1/solana/' in path:
                batch=path.rsplit('/',1)[1].split(',')
                return [ds_pair(m,pools[mints.index(m)]) for m in batch]
            self.fail(path)
        rows,health=discover(get=get,now=NOW)
        self.assertEqual(len(rows),100)
        self.assertEqual(health['raw_token_mints'],100)
        self.assertEqual(health['coverage_shortfall'],0)
        self.assertEqual(health['search_requests'],4)
        self.assertEqual(health['batch_requests'],4)
        self.assertEqual(len(seen),10)
        self.assertTrue(all(core.eligible(t) for t in rows))
        self.assertTrue(all(t.get('promotion_is_not_safety_approval') for t in rows))

    def test_no_rugcheck_bypass_on_promotion_and_bad_provider_data(self):
        def get(path):
            if 'token-profiles' in path:raise TimeoutError('offline')
            if 'token-boosts' in path:
                return [{'chainId':'solana','tokenAddress':MINTS[0]}]
            if '/tokens/' in path:return [ds_pair(MINTS[0],POOL_IDS[0],price='0')]
            self.fail(path)
        rows,h=discover(get=get,now=NOW)
        self.assertEqual(rows,[])
        self.assertEqual(h['qualified_pairs'],0)
        self.assertGreater(len(h['errors']),0)

    def test_production_wide_integration_rotates_screening_and_never_accepts_unscreened(self):
        # Inject a deterministic no-key DEX list; no real network/token API.
        gecko=[gecko_pool(('A' if i==0 else chr(66+i))*32,
                          MINTS[i%len(MINTS)]) for i in range(5)]
        dex=[choose_pair(ds_pair(MINTS[i],POOL_IDS[i]),NOW)
             for i in range(5,len(MINTS))]
        fetched=[]
        def backend(endpoint,params=None):
            fetched.append(endpoint)
            if endpoint.endswith('/trending_pools'):
                return {'data':gecko if params.get('page')==1 else []}
            if endpoint.endswith('/trades'):
                return {'data':[]}
            raise AssertionError(endpoint)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json'
            with (mock.patch.object(core,'api',side_effect=backend) as provider,
                  mock.patch('agent.opportunity_discovery.discover',
                             return_value=(dex,{'raw_token_mints':len(dex),'qualified_pairs':len(dex),'errors':[]})),
                  mock.patch('agent.news.refresh'),
                  mock.patch('agent.strategies.run'),
                  mock.patch('agent.whales.whale_cycle')):
                provider.__name__='api'  # Exercise actual production discovery branch.
                result=core.run_cycle(fetch=provider,path=path,screen_token=lambda _:True)
            health=result['cycle_health']
            self.assertGreaterEqual(health['discoveries_eligible_unique'],15)
            self.assertGreaterEqual(health['discovery_free_batch_tokens'],10)
            self.assertEqual(health['security_screened'],10)
            self.assertEqual(health['trade_feed_budget'],4)
            self.assertEqual(health['trade_feeds_attempted'],4)
            self.assertGreater(health['unscreened_discovery_candidates'],0)
            self.assertEqual(len(result['positions']),0)
            self.assertEqual(result['cash_gbp'],2000)
            self.assertEqual(len(result['closed']),0)
            self.assertEqual(sum(e.endswith('/trades') for e in fetched),4)
            self.assertEqual(sum('trending_pools' in e for e in fetched),2)


if __name__=='__main__':unittest.main()
