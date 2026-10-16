import copy
import datetime as dt
import json
import sys
import types
import unittest
from unittest import mock

# On the actual GitHub repository, import its real core and patch only within
# individual tests. The standalone installer bundle can use an isolated stub.
try:
    from agent import core as active_core
except ImportError:
    active_core=types.ModuleType('agent.core')
    active_core.BASE='https://api.geckoterminal.com/api/v2'
    active_core.HEADERS={'Accept':'application/json;version=20230203'}
    active_core.api=lambda *args,**kwargs: None
    sys.modules['agent.core']=active_core

from agent import whales

NOW=dt.datetime(2026,10,16,12,0,tzinfo=dt.timezone.utc)
MINT='A'*32
TOKEN='B'*32
WALLET='C'*32

def pool(token=TOKEN, mint=MINT, price=1.0):
    return dict(pool=token,mint=mint,price_usd=price,name='TEST/SOL',age_hours=240,
                liquidity_usd=500000,volume_24h_usd=3000000,change_24h_pct=10)

def ev(idx=1,kind='buy',usd=55000,token=TOKEN,wallet=WALLET,seconds=45):
    return dict(id=f'tx-{idx}:{kind}:{token}',wallet=wallet,kind=kind,token=token,usd=usd,
                timestamp=NOW-dt.timedelta(seconds=seconds),pool_name='TEST/SOL')

def state():
    return dict(paper_only=True, starting_gbp=2000.0, cash_gbp=1988.9,
                initialized_at='2026-10-15T22:18:05+00:00',
                last_run=(NOW-dt.timedelta(minutes=5)).isoformat(),
                completed_cycles=9,watched_pools=[pool()],
                positions=[{'token':'LIVE-POSITION','wallet':'existing','cost_gbp':11.1}],
                closed=[{'wallet':'historical','net_pnl_gbp':.7}],
                research={'shadow_positions':[{'some':'V2 only'}]})

def offline_fetch(path,params=None):
    if 'trending_pools' in path:return {'data':[]}
    if '/multi/' in path:return {'data':[]}
    if path.endswith('/trades'):return {'data':[]}
    return {'data':{}}

class WhaleResearch(unittest.TestCase):
    def setUp(self):
        self.core_patches = [
            mock.patch.object(active_core,'pool_meta',lambda raw:copy.deepcopy(raw.get('meta',raw)),create=True),
            mock.patch.object(active_core,'eligible',lambda m:m.get('liquidity_usd',0)>=100000 and m.get('volume_24h_usd',0)>=150000 and (m.get('price_usd') or 0)>0 and bool(m.get('mint')) and m.get('age_hours',0)>=24,create=True),
            mock.patch.object(active_core,'extract_event',lambda raw,pool:raw.get('event'),create=True),
        ]
        for patcher in self.core_patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.s=state()
        self.protected={k:copy.deepcopy(self.s[k]) for k in ('paper_only','starting_gbp','cash_gbp','initialized_at','positions','closed')}
    def scan(self,events=(),price=1.0,screener=lambda _: {'allowed':True,'status':'PASS'},current=NOW,fetch=offline_fetch):
        return whales.whale_cycle(self.s,[pool()],list(events),{TOKEN:price},current,fetch=fetch,screener=screener)
    def unchanged(self):
        for k,v in self.protected.items():self.assertEqual(self.s[k],v,'Protected field changed: '+k)
    def test_large_single_flow_discovered_but_not_assumed_profitable(self):
        w=self.scan([ev(1,usd=11000)])
        self.assertEqual(w['scanner']['large_flows'],1)
        self.assertEqual(w['shadow_positions'],[])
        self.assertFalse(w['owner_identity_verified'])
        self.assertEqual(w['sender_profiles'][WALLET]['buys'],1)
        self.unchanged()
    def test_repeated_large_wallet_opens_shadow_without_touching_paper_account(self):
        w=self.scan([ev(1,usd=12000,seconds=60),ev(2,usd=14000,seconds=40)])
        self.assertEqual(len(w['shadow_positions']),1)
        self.assertEqual(w['shadow_positions'][0]['strategy'],'large_repeat')
        self.assertEqual(w['shadow_positions'][0]['notional_gbp'],10)
        self.assertEqual(w['shadow_positions'][0]['signal_features']['wallet_identity_verified'],False)
        self.unchanged()
    def test_big_flow_opens_very_large_shadow(self):
        w=self.scan([ev(1,usd=60000)])
        self.assertEqual([p['strategy'] for p in w['shadow_positions']],['very_large'])
    def test_whale_shadow_closes_only_from_later_quote_and_books_costs(self):
        w=self.scan([ev(1,usd=60000)])
        self.assertEqual(len(w['shadow_closed']),0)
        self.s['completed_cycles']=10
        w=self.scan([],price=1.3,current=NOW+dt.timedelta(minutes=5))
        self.assertEqual(len(w['shadow_positions']),0)
        self.assertEqual(len(w['shadow_closed']),1)
        self.assertAlmostEqual(w['shadow_closed'][0]['net_pnl_gbp'],2.77,places=2)
        self.assertEqual(w['shadow_reports']['very_large']['status'],'COLLECTING_EVIDENCE')
        self.assertEqual(w['sender_shadow_reports'][WALLET]['closed'],1)
        self.assertFalse(w['sender_shadow_reports'][WALLET]['eligible_for_real_paper_sizing'])
        self.unchanged()
    def test_no_false_mark_when_missing_price(self):
        self.scan([ev(1,usd=60000)])
        w=self.scan([],price=None,current=NOW+dt.timedelta(minutes=5))
        self.assertEqual(len(w['shadow_positions']),1)
        self.assertEqual(len(w['shadow_closed']),0)
        self.assertEqual(w['shadow_mark_health'][TOKEN],'UNPRICED')
    def test_no_trade_on_conflicting_buy_sell(self):
        w=self.scan([ev(1,usd=60000),ev(2,kind='sell',usd=12000)])
        self.assertEqual(w['shadow_positions'],[])
    def test_sub_10k_sell_in_base_feed_suppresses_large_buy(self):
        w=self.scan([ev(1,usd=60000),ev(2,kind='sell',usd=500)])
        self.assertEqual(w['shadow_positions'],[])
    def test_cost_sensitivity_is_measured_without_changing_original_account(self):
        self.scan([ev(1,usd=60000)])
        w=self.scan([],price=1.3,current=NOW+dt.timedelta(minutes=5))
        report=w['shadow_reports']['very_large']
        self.assertLess(report['net_gbp_at_2pct_each_side'],report['net_gbp'])
        self.assertLess(report['net_gbp_at_5pct_each_side'],report['net_gbp_at_2pct_each_side'])
        self.unchanged()
    def test_safety_unavailable_fails_closed(self):
        w=self.scan([ev(1,usd=60000)],screener=lambda _: {'status':'UNAVAILABLE','allowed':False})
        self.assertEqual(w['shadow_positions'],[])
    def test_stale_event_cannot_open_shadow(self):
        w=self.scan([ev(1,usd=60000,seconds=300)])
        self.assertEqual(w['shadow_positions'],[])
        self.assertFalse(w['recent_flows'][0]['fresh'])
    def test_duplicate_swap_id_counted_once(self):
        w=self.scan([ev(1,usd=60000),ev(1,usd=60000)])
        self.assertEqual(len(w['recent_flows']),1)
        self.assertEqual(w['scanner']['very_large_flows'],1)
    def test_accumulation_requires_three_buys_and_positive_net_flow(self):
        w=self.scan([ev(1,usd=11000,seconds=90),ev(2,usd=12000,seconds=70),ev(3,usd=13000,seconds=50)])
        self.assertEqual(set(x['strategy'] for x in w['shadow_positions']),{'large_repeat','accumulation'})
    def test_screening_exception_does_not_open(self):
        def broken(_):raise RuntimeError('risk provider unavailable')
        w=self.scan([ev(1,usd=60000)],screener=broken)
        self.assertEqual(w['shadow_positions'],[])
        self.assertTrue(w['last_scan_errors'])
    def test_extra_pool_discovery_with_current_quote_and_fresh_swap(self):
        extra='D'*32;mint='E'*32
        extra_meta=pool(extra,mint,price=1.2)
        def fetch(path,params=None):
            if 'trending_pools' in path:return {'data':[{'meta':extra_meta}]}
            if '/multi/' in path:return {'data':[{'meta':extra_meta}]}
            if path.endswith('/trades'):
                return {'data':[{'event':ev(31,usd=65000,token=extra)}]}
            return {'data':{}}
        w=self.scan([],fetch=fetch)
        self.assertEqual(w['scanner']['additional_pools'],1)
        self.assertEqual(len(w['shadow_positions']),1)
        self.assertEqual(w['shadow_positions'][0]['source'],'extra_pool')
        self.assertEqual(w['shadow_positions'][0]['entry_price_usd'],1.2)
        self.unchanged()
    def test_quote_failure_skips_extra_entries_and_degrades_whale_only(self):
        extra='D'*32
        def fetch(path,params=None):
            if 'trending_pools' in path:return {'data':[{'meta':pool(extra,'E'*32)}]}
            if '/multi/' in path:raise TimeoutError('free quote cache unavailable')
            return {'data':[]}
        w=self.scan([],fetch=fetch)
        self.assertEqual(w['status'],'DEGRADED')
        self.assertEqual(w['shadow_positions'],[])
        self.unchanged()
    def test_baseline_no_reinforcement_without_proven_result(self):
        w=self.scan([ev(1,usd=60000)])
        self.assertEqual(w['shadow_sizing']['very_large'],.005)
        self.assertEqual(w['shadow_sizing_events'],[])
    def test_single_lucky_big_win_not_sufficient(self):
        r=whales.initialize(self.s)
        r['shadow_closed']=[{'strategy':'very_large','net_pnl_gbp':1000,'roi_pct':1000,'wallet':'w','token':'t','signal_id':'s','exit_at':NOW.isoformat()}]
        whales._update_reports(r,NOW)
        self.assertEqual(r['shadow_sizing']['very_large'],.005)
    def test_robust_shadow_outcomes_can_reinforce_shadow_only(self):
        r=whales.initialize(self.s)
        # 45 independently closed positive trades over 15 days from 15 senders, 5 pools.
        r['shadow_closed']=[{'strategy':'very_large','net_pnl_gbp':.25,'roi_pct':2.45,
            'wallet':f'w{i%15}','token':f'pool{i%5}','signal_features':{'mint':f'mint{i%5}'},'signal_id':f'signal{i}',
            'exit_at':(NOW+dt.timedelta(days=i%15)).isoformat()} for i in range(45)]
        whales._update_reports(r,NOW+dt.timedelta(days=16))
        self.assertEqual(r['shadow_reports']['very_large']['status'],'COLLECTING_EVIDENCE')
        r['oos_validation']={'very_large':True}
        whales._update_reports(r,NOW+dt.timedelta(days=16))
        self.assertEqual(r['shadow_reports']['very_large']['status'],'SHADOW_REINFORCED')
        self.assertEqual(r['shadow_sizing']['very_large'],.0075)
        self.assertFalse(r['shadow_reports']['very_large']['paper_account_promoted'])
        self.unchanged()
    def test_duplicate_strategy_outcomes_not_independent_sender_wins(self):
        r=whales.initialize(self.s)
        original={'strategy':'very_large','net_pnl_gbp':2,'roi_pct':19.8,
                  'wallet':WALLET,'token':TOKEN,'signal_id':'same-tx',
                  'exit_at':NOW.isoformat()}
        r['shadow_closed']=[original,{**original,'strategy':'large_repeat'}]
        whales._update_reports(r,NOW)
        self.assertEqual(r['sender_shadow_reports'][WALLET]['closed'],1)
        self.assertFalse(r['sender_shadow_reports'][WALLET]['eligible_for_real_paper_sizing'])
    def test_missing_diversity_prevents_promotion(self):
        r=whales.initialize(self.s)
        r['shadow_closed']=[{'strategy':'very_large','net_pnl_gbp':.25,'roi_pct':2.45,
            'wallet':'one-wallet','token':'one-pool','signal_features':{'mint':'one'},'signal_id':f'id{i}',
            'exit_at':(NOW+dt.timedelta(days=i%15)).isoformat()} for i in range(45)]
        whales._update_reports(r,NOW+dt.timedelta(days=16))
        self.assertEqual(r['shadow_sizing']['very_large'],.005)
    def test_json_serializable_and_bounded(self):
        w=self.scan([ev(1,usd=60000)])
        json.dumps(self.s,allow_nan=False)
        self.assertLessEqual(len(w['observed_ids']),whales.MAX_EVENT_IDS)
        self.unchanged()


class WhaleIntegrationRegressions(unittest.TestCase):
    def test_real_core_hook_passes_previous_timestamp_to_supplemental_scan(self):
        import tempfile
        from pathlib import Path
        from agent import core
        now=dt.datetime.now(core.UTC)
        token,mint='D'*32,'E'*32
        def raw_pool(address,mint):
            return dict(id='solana_'+address,relationships={'base_token':{'data':{'id':'solana_'+mint}}},
                attributes=dict(address=address,name='TEST/SOL',reserve_in_usd='500000',volume_usd={'h24':'3000000'},
                base_token_price_usd='1.2',pool_created_at=(now-dt.timedelta(days=10)).isoformat()))
        base=raw_pool(TOKEN,MINT);extra=raw_pool(token,mint)
        trade=dict(attributes=dict(tx_hash='real-core-extra',tx_from_address=WALLET,kind='buy',
            block_timestamp=(now-dt.timedelta(seconds=15)).isoformat(),volume_in_usd='65000'))
        def fetch(path,params=None):
            if 'trending_pools' in path:return {'data':[extra if params.get('page')==2 else base]}
            if '/multi/' in path:return {'data':[extra]}
            if path.endswith('/trades'):return {'data':[trade] if token in path else []}
            return {'data':extra}
        state=core.blank_state();state['last_run']=(now-dt.timedelta(minutes=5)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json';core.save(state,path)
            result=core.run_cycle(fetch=fetch,path=path,screen_token=lambda _:True)
            self.assertEqual(core.load(path),result)
        w=result['research']['whale_v3']
        self.assertEqual(w['scanner']['large_flows'],1)
        self.assertEqual(w['shadow_positions'][0]['source'],'extra_pool')
        self.assertEqual(result['cash_gbp'],2000)
        self.assertEqual(result['positions'],[])
        self.assertEqual(result['closed'],[])
        self.assertEqual(result['last_status'],'OK')

    def test_provider_unavailable_stays_distinct_from_rejection(self):
        r=whales.initialize(state())
        self.assertFalse(whales.risk_allowed(r,MINT,NOW,lambda _:{'allowed':False,'status':'UNAVAILABLE'}))
        self.assertEqual(r['safety_cache'][MINT]['status'],'UNAVAILABLE')
        self.assertTrue(r['last_scan_errors'])

    def test_whale_cycle_cannot_mutate_v2_research_or_account(self):
        s=state();before=copy.deepcopy(s)
        whales.whale_cycle(s,[pool()],[ev()],{TOKEN:1},NOW,fetch=offline_fetch,screener=lambda _:True)
        del s['research']['whale_v3']
        self.assertEqual(s,before)

    def test_v3_exception_still_persists_original_paper_cycle(self):
        import tempfile
        from pathlib import Path
        from agent import core
        s=core.blank_state();s['last_run']=(dt.datetime.now(core.UTC)-dt.timedelta(minutes=5)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json';core.save(s,path)
            with mock.patch.object(whales,'whale_cycle',side_effect=TimeoutError('isolated timeout')):
                result=core.run_cycle(fetch=lambda *a:{'data':[]},path=path,screen_token=lambda _:False)
            self.assertEqual(core.load(path),result)
        self.assertEqual(result['cash_gbp'],s['cash_gbp'])
        self.assertEqual(result['initialized_at'],s['initialized_at'])
        self.assertEqual(result['completed_cycles'],1)
        self.assertEqual(result['research']['whale_v3']['status'],'DEGRADED')
        self.assertEqual(result['last_status'],'NO_ELIGIBLE_POOLS')

    def test_missing_supplemental_quote_is_degraded_without_entries(self):
        s=state();s['completed_cycles']=10
        r=whales.initialize(s);r['watched_pools']=[pool('D'*32,'E'*32)]
        result=whales.whale_cycle(s,[],[],{},NOW,fetch=offline_fetch,screener=lambda _:True)
        self.assertEqual(result['status'],'DEGRADED')
        self.assertTrue(any('fresh supplemental quote missing' in x for x in result['last_scan_errors']))
        self.assertEqual(result['shadow_positions'],[])

    def test_supplemental_small_sell_suppresses_large_shadow_buy(self):
        s=state();token,mint='D'*32,'E'*32;extra=pool(token,mint)
        def fetch(path,params=None):
            if 'trending_pools' in path or '/multi/' in path:return {'data':[extra]}
            if path.endswith('/trades'):
                self.assertEqual(params['trade_volume_in_usd_greater_than'],100)
                return {'data':[{'event':ev(71,usd=65000,token=token)}, {'event':ev(72,usd=500,token=token,kind='sell')}]}
            return {'data':{}}
        with mock.patch.object(active_core,'pool_meta',lambda raw:raw), mock.patch.object(active_core,'extract_event',lambda raw,p:raw['event']):
            result=whales.whale_cycle(s,[],[],{},NOW,fetch=fetch,screener=lambda _:True)
        self.assertEqual(result['scanner']['large_flows'],1)
        self.assertEqual(result['shadow_positions'],[])

    def test_missing_shadow_mark_is_not_displayed_as_current(self):
        r=whales.initialize(state())
        r['shadow_positions']=[dict(wallet=WALLET,token=TOKEN,last_mark_price_usd=1)]
        whales._mark_open(r,{},[],NOW)
        self.assertIsNone(r['shadow_positions'][0]['last_mark_price_usd'])
        self.assertEqual(r['shadow_mark_health'][TOKEN],'UNPRICED')
        self.assertTrue(r['last_scan_errors'])
        self.assertEqual(r['shadow_closed'],[])

if __name__=='__main__':unittest.main()
