import copy
import datetime as dt
import io
import unittest
import urllib.error
from unittest.mock import patch
from agent import core, evaluation, research_feed, whales

UTC=dt.timezone.utc
NOW=dt.datetime(2026,10,16,14,tzinfo=UTC)

class Clock:
    def __init__(self):self.value=0
    def __call__(self):return self.value
    def sleep(self,n):self.value+=n

class FeedBudget(unittest.TestCase):
    def feed(self,r=None,transport=None):
        self.r=r if r is not None else {'scan_metrics':{}}
        self.clock=Clock()
        return research_feed.ResearchFeed(self.r,NOW,transport=transport or (lambda *a:{'data':[]}),clock=self.clock,sleep=self.clock.sleep)

    def test_request_budget_and_pacing(self):
        f=self.feed()
        for _ in range(4):f('/trades')
        with self.assertRaises(research_feed.Deferred):f('/trades')
        self.assertEqual(f.requests,4)
        self.assertGreaterEqual(self.clock.value,6.3)

    def test_429_cooldown_survives_runner_and_honours_retry_after(self):
        calls=[]
        def transport(*args):
            calls.append(args);raise urllib.error.HTTPError('u',429,'rate limited',{'Retry-After':'900'},io.BytesIO())
        f=self.feed(transport=transport)
        with self.assertRaises(urllib.error.HTTPError):f('/pool/trades')
        restored=research_feed.ResearchFeed(copy.deepcopy(self.r),NOW+dt.timedelta(minutes=5),transport=transport,clock=self.clock,sleep=self.clock.sleep)
        with self.assertRaises(research_feed.Deferred):restored('/pool/trades')
        self.assertEqual(len(calls),1)
        later=research_feed.ResearchFeed(self.r,NOW+dt.timedelta(minutes=16),transport=transport,clock=self.clock,sleep=self.clock.sleep)
        with self.assertRaises(urllib.error.HTTPError):later('/pool/trades')
        self.assertEqual(self.r['provider_health']['gecko_trades']['consecutive_failures'],2)

    def test_exponential_cooldown_without_header(self):
        r={'scan_metrics':{}}
        for attempt,minutes in [(0,0),(1,6),(2,17)]:
            f=research_feed.ResearchFeed(r,NOW+dt.timedelta(minutes=minutes),transport=lambda *a: (_ for _ in ()).throw(TimeoutError('timeout')),clock=Clock(),sleep=lambda n:None)
            with self.assertRaises(TimeoutError):f('/trades')
            until=research_feed.stamp(r['provider_health']['gecko_trades']['retry_at'])
            self.assertEqual((until-(NOW+dt.timedelta(minutes=minutes))).total_seconds(),300*2**attempt)

    def test_cache_only_discovery_never_reuses_quotes_as_current(self):
        calls=[]
        f=self.feed(transport=lambda *a:(calls.append(a) or {'data':[]}))
        for _ in range(2):f('/trending_pools',{'page':2})
        for _ in range(2):f('/pools/multi/x')
        self.assertEqual(len(calls),3)
        self.assertEqual(self.r['scan_metrics']['cache_hits'],1)

    def test_time_budget_fail_closed(self):
        f=self.feed();self.clock.value=21
        with self.assertRaises(research_feed.Deferred):f('/x')
        self.assertEqual(f.requests,0)

    def test_quote_fallback_cannot_fabricate_wallet_events(self):
        f=self.feed()
        payload={'pairs':[{'chainId':'solana','pairAddress':'P','baseToken':{'address':'A'*32,'symbol':'X'},'quoteToken':{'symbol':'SOL'},'priceUsd':'1.25','liquidity':{'usd':500000},'volume':{'h24':900000},'pairCreatedAt':int((NOW-dt.timedelta(days=10)).timestamp()*1000)}, {'chainId':'ethereum','pairAddress':'P'}]}
        with patch.object(research_feed,'public_json',return_value=payload):out=f.fallback_quotes(['P'])
        self.assertEqual(len(out['data']),1)
        self.assertEqual(core.pool_meta(out['data'][0])['price_usd'],1.25)
        self.assertIsNone(core.extract_event(out['data'][0],{'pool':'P','name':'X'}))

    def test_malformed_response_trips_persistent_circuit(self):
        f=self.feed(transport=lambda *a:{'data':None})
        with self.assertRaises(ValueError):f('/pool/trades')
        self.assertIsNotNone(self.r['provider_health']['gecko_trades']['retry_at'])

class ForwardEvaluation(unittest.TestCase):
    def trades(self):
        out=[]
        for i in range(60):
            opened=NOW+dt.timedelta(days=i,hours=1)
            out.append(dict(signal_id=str(i),wallet='W'+str(i%10),token='P'+str(i%5),
                opened_at=opened.isoformat(),exit_at=(opened+dt.timedelta(hours=1)).isoformat(),
                entry_price_usd=1,exit_price_usd=1.10,notional_gbp=10,
                net_pnl_gbp=.79,roi_pct=7.82))
        return out

    def test_fixed_forward_split_and_cost_stress(self):
        report=evaluation.evaluate(self.trades(),NOW.isoformat())
        self.assertEqual(report['status'],'VALIDATED_OOS')
        self.assertEqual(report['training']['closed'],40)
        self.assertEqual(report['validation']['closed'],20)
        self.assertGreater(report['validation']['cost_stress']['2pct_each_side_mean_roi_pct'],0)
        self.assertFalse(report['automatic_strategy_promotion'])

    def test_old_closes_and_duplicates_cannot_certify(self):
        t=self.trades()
        self.assertEqual(evaluation.evaluate(t,(NOW+dt.timedelta(days=80)).isoformat())['training']['closed'],0)
        self.assertEqual(evaluation.evaluate([t[0]]*100,NOW.isoformat())['training']['closed'],1)

    def test_white_paper_p0_fast_first_twenty_then_later_days_can_validate(self):
        # The first 20 validation closes all occur on the first day;
        # previously the permanent [:20] prevented later days qualifying.
        from agent import evaluation
        train=[]
        for i in range(40):
            entered=NOW+dt.timedelta(days=i%14,hours=i//14)
            train.append(dict(signal_id='train'+str(i),wallet='W'+str(i%10),
                token='P'+str(i%5),opened_at=entered.isoformat(),
                exit_at=(entered+dt.timedelta(minutes=20)).isoformat(),
                entry_price_usd=1.,exit_price_usd=1.15,net_pnl_gbp=1.28,
                notional_gbp=10.,roi_pct=12.8))
        train.sort(key=lambda t:t['exit_at'])
        cutoff=max(evaluation.stamp(t['exit_at']) for t in train)
        validation=[]
        for i in range(20):
            opened=cutoff+dt.timedelta(hours=2,minutes=i)
            validation.append(dict(signal_id='rapid'+str(i),wallet='W'+str(i%10),
                token='P'+str(i%5),opened_at=opened.isoformat(),
                exit_at=(opened+dt.timedelta(minutes=1)).isoformat(),
                entry_price_usd=1.,exit_price_usd=1.15,net_pnl_gbp=1.28,
                notional_gbp=10.,roi_pct=12.8))
        early=evaluation.evaluate(train+validation,NOW.isoformat())
        self.assertEqual(early['status'],'UNPROVEN')
        self.assertFalse(early['validation_prefix_complete'])
        self.assertEqual(early['validation']['days'],1)
        self.assertEqual(len(early['validation_ids']),20)
        for day in range(1,7):
            opened=cutoff+dt.timedelta(days=day,hours=2)
            validation.append(dict(signal_id='later'+str(day),wallet='W'+str(day),
                token='P'+str(day%5),opened_at=opened.isoformat(),
                exit_at=(opened+dt.timedelta(minutes=20)).isoformat(),
                entry_price_usd=1.,exit_price_usd=1.15,net_pnl_gbp=1.28,
                notional_gbp=10.,roi_pct=12.8))
        fixed=evaluation.evaluate(train+validation,NOW.isoformat())
        self.assertTrue(fixed['validation_prefix_complete'])
        self.assertEqual(fixed['validation']['days'],7)
        self.assertEqual(len(fixed['validation_ids']),26)
        self.assertEqual(fixed['status'],'VALIDATED_OOS')
        # Later outcomes cannot cherry-pick a new winning cohort.
        late=dict(validation[-1],signal_id='after',opened_at=(cutoff+dt.timedelta(days=8)).isoformat(),
                  exit_at=(cutoff+dt.timedelta(days=8,minutes=20)).isoformat(),net_pnl_gbp=-10,roi_pct=-100)
        unchanged=evaluation.evaluate(train+validation+[late],NOW.isoformat())
        self.assertEqual(fixed['evidence_hash'],unchanged['evidence_hash'])

    def test_overlapping_validation_entries_are_purged(self):
        t=self.trades()
        for x in t[40:]:x['opened_at']=t[0]['opened_at']
        self.assertEqual(evaluation.evaluate(t,NOW.isoformat())['validation']['closed'],0)

    def test_holdout_losses_block_positive_training(self):
        t=self.trades()
        for x in t[40:]:x.update(net_pnl_gbp=-1,roi_pct=-10,exit_price_usd=.9)
        self.assertEqual(evaluation.evaluate(t,NOW.isoformat())['status'],'UNPROVEN')

    def test_missing_cost_prices_never_certify(self):
        t=self.trades();del t[50]['exit_price_usd']
        self.assertEqual(evaluation.evaluate(t,NOW.isoformat())['status'],'UNPROVEN')

    def test_correlated_same_day_sample_insufficient(self):
        t=self.trades()
        for x in t:x['opened_at']=t[0]['opened_at'];x['exit_at']=t[0]['exit_at']
        self.assertEqual(evaluation.evaluate(t,NOW.isoformat())['status'],'UNPROVEN')

    def test_sparse_or_one_pool_validation_never_certifies(self):
        t=self.trades()
        for x in t:x['token']='same'
        self.assertEqual(evaluation.evaluate(t,NOW.isoformat())['status'],'UNPROVEN')

    def test_registration_no_retroactive_learning_or_account_mutation(self):
        s=core.blank_state();s['closed']=self.trades();b=copy.deepcopy(s)
        r=evaluation.update(s,NOW+dt.timedelta(days=80))
        self.assertEqual(r['validated_reports'],0)
        for key in b:self.assertEqual(s[key],b[key])

    def test_frozen_cohort_change_invalidates_permanently(self):
        s={'closed':self.trades(),'research':{}}
        evaluation.initialize(s,NOW);evaluation.update(s,NOW+dt.timedelta(days=61))
        self.assertEqual(s['research']['evaluation_v1']['reports']['actual:all']['status'],'VALIDATED_OOS')
        s['closed'][45]['signal_id']='changed'
        for _ in range(2):
            r=evaluation.update(s,NOW+dt.timedelta(days=62))
            self.assertEqual(r['reports']['actual:all']['status'],'UNPROVEN')
            self.assertTrue(r['reports']['actual:all']['invalidated'])

    def test_observed_flow_outcomes_not_wallet_profit(self):
        r={};flows=[{'event_id':'tx','wallet':'W','token':'P','fresh':True,'kind':'buy'}]
        evaluation.observe_whales(r,flows,{'P':1},NOW)
        evaluation.observe_whales(r,[],{'P':1.1},NOW+dt.timedelta(minutes=61))
        self.assertEqual(len(r['flow_outcomes']),1)
        result=r['flow_outcomes'][0]
        self.assertAlmostEqual(result['marks']['60m']['quote_return_pct'],10)
        self.assertFalse(result['wallet_profit_verified'])
        self.assertNotIn('net_pnl_gbp',result)

    def test_historical_flow_has_no_backfilled_return(self):
        r={};evaluation.observe_whales(r,[{'event_id':'old','token':'P','fresh':False}],{'P':1},NOW)
        self.assertEqual(r['flow_followups'],[])

    def test_missing_observation_quote_no_fictional_outcome(self):
        r={};evaluation.observe_whales(r,[{'event_id':'tx','wallet':'W','token':'P','fresh':True,'kind':'buy'}],{'P':1},NOW)
        evaluation.observe_whales(r,[],{},NOW+dt.timedelta(minutes=61))
        self.assertEqual(r['flow_outcomes'],[])
        self.assertEqual(r['flow_followups'][0]['marks'],{})

if __name__=='__main__':unittest.main()

class CoverageAndAttribution(unittest.TestCase):
    def test_registry_reuses_primary_inventory_and_rotates(self):
        def meta(name):return dict(pool=name,mint='A'*32,price_usd=1,liquidity_usd=500000,volume_24h_usd=1000000,age_hours=100)
        s={'completed_cycles':1,'watched_pools':[meta('core')]}
        r={'watched_pools':[meta('old')],'shadow_positions':[],'recent_flows':[]}
        def no_discovery(*args):raise AssertionError('unnecessary discovery request')
        whales._pick_watchlist(s,no_discovery,r,[meta('core'),meta('new1'),meta('new2'),meta('new3')])
        first={p['pool'] for p in r['watched_pools']}
        for p in first:r['pool_last_scanned'][p]=NOW.isoformat()
        whales._pick_watchlist(s,no_discovery,r,[])
        self.assertNotEqual(first,{p['pool'] for p in r['watched_pools']})
        self.assertNotIn('core',{p['pool'] for p in r['watched_pools']})

    def test_old_large_transaction_discovery_never_fresh_entry(self):
        s={};r=whales.initialize(s)
        ev={'id':'tx:buy:P','wallet':'W','token':'P','kind':'buy','usd':60000,'timestamp':NOW-dt.timedelta(minutes=1),'research_only':True}
        flows=whales._dedup_flows(s,[],[ev],NOW,{})
        self.assertEqual(len(flows),1);self.assertFalse(flows[0]['fresh'])
        self.assertEqual(whales.candidates_from_flows(r,flows,NOW),[])
        self.assertEqual(flows[0]['transaction_hash'],'tx')

    def test_sender_multi_pool_flag_is_not_owner_verification(self):
        r={};events=[dict(id=str(i),wallet='W',token='P'+str(i),kind='buy',timestamp=NOW) for i in range(3)]
        whales._observe_activity(r,events,NOW);whales._observe_activity(r,events,NOW)
        p=r['sampled_activity']['W'];self.assertEqual(p['buys'],3)
        self.assertEqual(p['attribution'],'MULTI_POOL_OR_ROUTER_POSSIBLE')
        self.assertFalse(p['identity_verified'])

class EvaluationFailureIsolation(unittest.TestCase):
    def test_research_exception_revokes_certificates_without_changing_account(self):
        s={'cash_gbp':1990,'positions':[{'signal_id':'original'}],'closed':[],'research':{}}
        before=copy.deepcopy(s)
        with patch.object(evaluation,'update',side_effect=RuntimeError('unavailable')):
            r=evaluation.safe_update(s,NOW)
        self.assertEqual(r['status'],'DEGRADED');self.assertEqual(r['reports'],{})
        self.assertFalse(evaluation.certified(s,'wallet:test'))
        for key in ['cash_gbp','positions','closed']:self.assertEqual(s[key],before[key])

class ProviderWindow(unittest.TestCase):
    def test_primary_window_delay_is_bounded_and_not_a_retry(self):
        self.assertEqual(research_feed.primary_window_delay(NOW,NOW),60)
        self.assertEqual(research_feed.primary_window_delay(NOW,NOW+dt.timedelta(seconds=10)),55)
        self.assertEqual(research_feed.primary_window_delay(NOW,NOW+dt.timedelta(seconds=70)),0)

    def test_injected_transport_never_sleeps_primary_window(self):
        clock=Clock();r={'scan_metrics':{}}
        with patch.dict('os.environ',{'GITHUB_ACTIONS':'true'}):
            research_feed.ResearchFeed(r,NOW,transport=lambda *a:{'data':[]},clock=clock,sleep=clock.sleep)
        self.assertEqual(clock.value,0)
        self.assertEqual(r['scan_metrics']['primary_window_wait_seconds'],0)

    def test_research_deadline_starts_after_primary_window(self):
        clock=Clock();r={'scan_metrics':{}}
        with patch.dict('os.environ',{'GITHUB_ACTIONS':'true'}), patch.object(research_feed,'primary_window_delay',return_value=55), patch.object(whales,'fast_fetch',return_value={'data':[]}):
            f=research_feed.ResearchFeed(r,NOW,clock=clock,sleep=clock.sleep)
            self.assertEqual(f('/pool/trades'),{'data':[]})
        self.assertEqual(clock.value,55)
        self.assertEqual(r['scan_metrics']['primary_window_wait_seconds'],55)
        self.assertEqual(f.requests,1)
