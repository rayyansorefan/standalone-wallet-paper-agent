"""Regression and safety tests for evidence-driven paper-only optimisation."""
import datetime as dt
import unittest
from agent import adaptive

UTC=dt.timezone.utc
T=dt.datetime(2026,10,16,7,0,tzinfo=UTC)
W='A'*32
POOL='B'*32
MINT='C'*32

def paper_trade(pnl, index=0, wallet=W):
    exit_date = (T+dt.timedelta(days=index//3)).isoformat()
    return dict(wallet=wallet, net_pnl_gbp=pnl, token='T'+str(index%6),
                roi_pct=pnl*10, exit_at=exit_date, signal_id=str(index))

def state():
    return dict(starting_gbp=2000.0, cash_gbp=1989.9, positions=[{'token':'protected'}],
                closed=[], observed={W:{'count':10}}, screening=[{'mint':MINT,'status':'PASS'}],
                last_run=(T-dt.timedelta(minutes=5)).isoformat())

def pool():
    return dict(pool=POOL, name='SAMPLE/SOL', mint=MINT, liquidity_usd=400_000,
                volume_24h_usd=800_000, age_hours=100, change_24h_pct=12,
                price_usd=1)

def buy():
    return dict(wallet=W, token=POOL, kind='buy',id='sig1', timestamp=T-dt.timedelta(seconds=40),usd=200)

class EvidenceGates(unittest.TestCase):
    def test_insufficient_evidence_never_increases_risk(self):
        s=state();s['closed']=[paper_trade(2,i) for i in range(5)]
        self.assertEqual(adaptive.wallet_report(s,W)['risk_fraction'], 0.005)

    def test_repeated_winners_on_multiple_days_reinforce_within_legacy_cap(self):
        s=state();s['closed']=[paper_trade(1,i) for i in range(8)]
        self.assertEqual(adaptive.wallet_report(s,W)['risk_fraction'],0.005)
        s['research']={'evaluation_v1':{'version':1,'reports':{'wallet:'+W:{'status':'VALIDATED_OOS'}}}}
        rep=adaptive.wallet_report(s,W)
        self.assertEqual(rep['reinforcement_tier'],'reinforced_1')
        self.assertEqual(rep['risk_fraction'],0.010)
        s['closed']=[paper_trade(1,i) for i in range(15)]
        rep=adaptive.wallet_report(s,W)
        self.assertEqual(rep['reinforcement_tier'],'reinforced_2')
        self.assertEqual(rep['risk_fraction'],0.015)

    def test_single_lucky_outlier_cannot_trigger_promotion(self):
        s=state();s['closed']=[paper_trade(-0.3,i) for i in range(8)] + [paper_trade(20,9)]
        self.assertEqual(adaptive.wallet_report(s,W)['risk_fraction'],0.005)

    def test_loss_evidence_suspends_wallet(self):
        s=state();s['closed']=[paper_trade(-2,i) for i in range(3)]
        self.assertEqual(adaptive.wallet_report(s,W)['risk_fraction'],0.0)

    def test_same_cycle_conflict_detection(self):
        selling=dict(buy(),kind='sell',id='sig2')
        self.assertIn((W,POOL),adaptive.conflicting_keys([buy(),selling]))

    def test_shadow_never_modifies_cash_positions_or_paper_closures(self):
        s=state();cash=s['cash_gbp']; positions=list(s['positions']);closed=list(s['closed'])
        adaptive.research_cycle(s,[pool()],{POOL:1},[buy()],T)
        self.assertEqual(s['cash_gbp'],cash)
        self.assertEqual(s['positions'],positions)
        self.assertEqual(s['closed'],closed)
        self.assertEqual(len(s['research']['shadow_positions']),2)
        self.assertEqual(len(s['research']['signals']),1)
        self.assertFalse(s['research']['signals'][0]['wallet_identity_verified'])

    def test_shadow_forward_profit_is_counterfactual_not_account_pnl(self):
        s=state();adaptive.research_cycle(s,[pool()],{POOL:1},[buy()],T)
        t2=T+dt.timedelta(minutes=5)
        s['last_run']=T.isoformat()
        adaptive.research_cycle(s,[pool()],{POOL:1.3},[],t2)
        adaptive.finalize(s,t2)
        self.assertEqual(len(s['research']['shadow_closed']),2)
        self.assertGreater(s['research']['shadow_reports']['quality']['net_gbp'],0)
        self.assertEqual(s['research']['shadow_reports']['quality']['status'],'COLLECTING_EVIDENCE')
        self.assertEqual(s['cash_gbp'],1989.9)

    def test_shadow_flat_price_charges_both_sides(self):
        s=state();adaptive.research_cycle(s,[pool()],{POOL:1},[buy()],T)
        t2=T+dt.timedelta(hours=7)
        s['last_run']=T.isoformat()
        adaptive.research_cycle(s,[pool()],{POOL:1},[],t2)
        self.assertEqual(len(s['research']['shadow_closed']),2)
        self.assertTrue(all(abs(t['net_pnl_gbp']+0.2)<0.0001
                            for t in s['research']['shadow_closed']))
        self.assertEqual(s['cash_gbp'],1989.9)

    def test_shadow_feed_degradation_does_not_change_main_account_status(self):
        s=state();s['last_status']='OK';s['last_run']=T.isoformat()
        r=adaptive.ensure(s);r['cycle_errors']=['market quote unavailable']
        adaptive.finalize(s,T)
        self.assertEqual(s['last_status'],'OK')
        self.assertEqual(s['research']['last_status'],'SHADOW_DATA_DEGRADED')

    def test_missing_price_does_not_fabricate_trade_closure(self):
        s=state();adaptive.research_cycle(s,[pool()],{POOL:1},[buy()],T)
        adaptive.research_cycle(s,[pool()],{},[],T+dt.timedelta(hours=7))
        self.assertEqual(len(s['research']['shadow_positions']),2)
        self.assertFalse(s['research']['shadow_closed'])

    def test_unsafe_token_never_shadow_opened(self):
        s=state();s['screening']=[{'mint':MINT,'status':'UNAVAILABLE'}]
        adaptive.research_cycle(s,[pool()],{POOL:1},[buy()],T)
        self.assertEqual(s['research']['shadow_positions'],[])

    def test_bootstrap_not_backfilled_into_shadow_profit(self):
        s=state();s['last_run']=None
        adaptive.research_cycle(s,[pool()],{POOL:1},[buy()],T)
        self.assertEqual(s['research']['shadow_positions'],[])

    def test_pre_registered_cohorts_can_reinforce_future_trades_only(self):
        s=state()
        sample=dict(signal_id='sig1', liquidity_usd=400000,
                    change_24h_pct=12,signal_age_seconds=20)
        r=adaptive.ensure(s)
        r['signals']=[sample]
        self.assertEqual(adaptive.feature_risk_multiplier(s,dict(id='sig1'))[0],1.0)
        r['entry_features']={'s'+str(i):sample for i in range(42)}
        s['closed']=[dict(paper_trade(1,i,wallet='W'+str(i%12)),signal_id='s'+str(i),
                          exit_at=(T+dt.timedelta(days=i//2)).isoformat()) for i in range(42)]
        r['feature_reports']=adaptive.feature_reports(s)
        self.assertEqual(r['feature_reports']['liq:250k+']['status'],'POSITIVE_EVIDENCE')
        self.assertEqual(adaptive.feature_risk_multiplier(s,dict(id='sig1'))[0],1.0)
        r['evaluation_v1']={'version':1,'reports':{'feature:liq:250k+':{'status':'VALIDATED_OOS'}}}
        self.assertEqual(adaptive.feature_risk_multiplier(s,dict(id='sig1'))[0],1.25)
        self.assertEqual(s['cash_gbp'],1989.9)

    def test_proven_losses_reduce_risk_from_future_signal(self):
        s=state();r=adaptive.ensure(s)
        sample=dict(signal_id='sig1',liquidity_usd=400000,
                    change_24h_pct=12,signal_age_seconds=20)
        r['signals']=[sample]
        r['entry_features']={'s'+str(i):sample for i in range(42)}
        s['closed']=[dict(paper_trade(-1,i,wallet='W'+str(i%12)),signal_id='s'+str(i),
                          exit_at=(T+dt.timedelta(days=i//2)).isoformat()) for i in range(42)]
        r['feature_reports']=adaptive.feature_reports(s)
        self.assertEqual(r['feature_reports']['lag:fast']['status'],'NEGATIVE_EVIDENCE')
        self.assertEqual(adaptive.feature_risk_multiplier(s,dict(id='sig1'))[0],0.5)

    def test_extra_market_fields_never_fabricated(self):
        meta=adaptive.enrich_meta(dict(attributes={'volume_usd':{'h1':'1234'}}),pool())
        self.assertEqual(meta['volume_1h_usd'],1234)
        self.assertIsNone(meta['market_cap_usd'])
        self.assertIsNone(meta['change_5m_pct'])

    def test_wallet_attribution_unverified_and_diversity_gate(self):
        s=state();adaptive.observe_event(s,dict(buy(),kind='buy'),T,pool())
        self.assertEqual(s['research']['wallet_activity'][W]['buys'],1)
        rep=adaptive.wallet_report(s,W)
        self.assertFalse(rep['identity_verified'])

if __name__=='__main__': unittest.main()
