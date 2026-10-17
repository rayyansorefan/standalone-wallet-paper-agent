"""V4.1 forward diagnostics, miss attribution and evidence-gated recovery."""
import datetime as dt
import unittest
from agent import strategy_lab as lab
from agent import strategies as st

NOW=dt.datetime(2026,10,17,8,0,tzinfo=dt.timezone.utc)


def fixture():
    state={'paper_only':True,'cash_gbp':1988.11,'positions':[], 'closed':[],
           'research':{'news_v1':{'checked_at':NOW.isoformat(),
                'sources':{'coindesk':{'status':'OK'}},'risk_off':False}}}
    quotes={'PF_TESTUSD':{'bid':99.99,'ask':100.01,'mid':100.,'relativeFundingRate':.00001}}
    features={'PF_TESTUSD':dict(close=100,previous=99.9,atr=.3,ema_fast=99.9,
             ema_slow=99.5,r1h=.02,r15m=.004,volume_ratio=1.5,
             fade_volume_ratio=1,pump=.01,drawdown=0,peak_age=0,lower_closes=False)}
    return state,quotes,features


def closed_loss(i):
    return {'setup':'momentum_long','version':st.VERSION,'symbol':'OTHER',
            'exit_at':(NOW-dt.timedelta(minutes=30-i*10)).isoformat(),
            'net_usd':-2.,'risk_usd':5.,'stress_net_usd':-3.}


class ForwardDiagnostics(unittest.TestCase):
    def test_missed_winner_includes_reason_and_observed_after_costs(self):
        b={'version':st.VERSION}
        c={'symbol':'PF_TESTUSD','setup':'momentum_long','direction':1,
           'regime':'ACTIVE_TREND','rejection_reason':'COST_HURDLE'}
        q={'PF_TESTUSD':{'bid':99.99,'ask':100.01,'mid':100}}
        lab.observe_forward(b,NOW,q,[c])
        self.assertEqual(b['forward_signals'][0]['rejection_reason'],'COST_HURDLE')
        lab.observe_forward(b,NOW+dt.timedelta(minutes=60),
                            {'PF_TESTUSD':{'bid':103.,'ask':103.02,'mid':103.01}},[])
        report=b['missed_winners']
        self.assertEqual(report['winners'],1)
        self.assertEqual(report['evaluated'],1)
        self.assertEqual(report['top_missed'][0]['reason'],'COST_HURDLE')
        self.assertGreater(report['top_missed'][0]['net_quote_roi_pct'],0)
        self.assertIn('HYPOTHETICAL',report['top_missed'][0]['status'])

    def test_missed_loser_included_in_denominator_not_winner_table(self):
        b={'version':st.VERSION}
        c={'symbol':'PF_TESTUSD','setup':'momentum_short','direction':-1,
           'regime':'ACTIVE_TREND','rejection_reason':'NEWS_VETO'}
        q={'PF_TESTUSD':{'bid':99.99,'ask':100.01,'mid':100}}
        lab.observe_forward(b,NOW,q,[c])
        lab.observe_forward(b,NOW+dt.timedelta(minutes=60),
                            {'PF_TESTUSD':{'bid':102,'ask':102.02,'mid':102.01}},[])
        self.assertEqual(b['missed_winners']['evaluated'],1)
        self.assertEqual(b['missed_winners']['winners'],0)
        self.assertEqual(b['missed_winners']['losers_or_flat'],1)
        self.assertEqual(b['missed_winners']['top_missed'],[])

    def test_missing_outcome_not_a_win_or_loss(self):
        b={'version':st.VERSION}
        c={'symbol':'PF_TESTUSD','setup':'momentum_short','direction':-1,
           'regime':'MIXED_OR_QUIET','rejection_reason':'DAILY_LIMIT'}
        lab.observe_forward(b,NOW,{'PF_TESTUSD':{'bid':100,'ask':100.01}},[c])
        lab.observe_forward(b,NOW+dt.timedelta(minutes=72),{},[])
        self.assertEqual(b['missed_winners']['evaluated'],0)

    def test_rank_cost_and_feedback_affect_order(self):
        f={'close':100,'atr':.5,'volume_ratio':2}
        tight={'bid':99.99,'ask':100.01,'mid':100}
        wide={'bid':99.8,'ask':100.2,'mid':100}
        positive=lab.priority_score(5,f,tight,{'adjustment':.5},.1)
        negative=lab.priority_score(5,f,tight,{'adjustment':-1},-.1)
        self.assertGreater(positive,negative)
        self.assertGreater(positive,lab.priority_score(5,f,wide,{'adjustment':.5},.1))

    def test_pause_does_not_expire_without_recovery_evidence(self):
        b={'version':st.VERSION,'forward_signals':[]}
        rows=[closed_loss(i) for i in range(3)]
        first=lab.recovery_state(b,'momentum_long',NOW,rows)
        self.assertEqual(first['status'],'PAUSED')
        second=lab.recovery_state(b,'momentum_long',NOW+dt.timedelta(hours=26),rows)
        self.assertEqual(second['status'],'RETESTING')
        self.assertFalse(second['allowed'])

    def test_recovery_requires_new_nonentered_outcomes_across_two_days(self):
        b={'version':st.VERSION,'forward_signals':[]}
        rows=[closed_loss(i) for i in range(3)]
        lab.recovery_state(b,'momentum_long',NOW,rows)
        for hours in (26,27,50,51):
            when=NOW+dt.timedelta(hours=hours)
            b['forward_signals'].append({'at':when.isoformat(),
                 'setup':'momentum_long','rule_version':st.VERSION,
                 'decision':'OBSERVED_NOT_ENTERED',
                 'outcomes':{'60m':{'net_roi_pct':1.2}}})
        recovered=lab.recovery_state(b,'momentum_long',NOW+dt.timedelta(hours=53),rows)
        self.assertTrue(recovered['allowed'])
        self.assertEqual(recovered['status'],'RECOVERED')
        again=lab.recovery_state(b,'momentum_long',NOW+dt.timedelta(hours=54),rows)
        self.assertTrue(again['allowed'])

    def test_recovered_setup_suspends_again_on_three_new_losses(self):
        b={'version':st.VERSION,'forward_signals':[]}
        rows=[closed_loss(i) for i in range(3)]
        lab.recovery_state(b,'momentum_long',NOW,rows)
        for hours in (26,27,50,51):
            b['forward_signals'].append({'at':(NOW+dt.timedelta(hours=hours)).isoformat(),
                 'setup':'momentum_long','rule_version':st.VERSION,
                 'decision':'OBSERVED_NOT_ENTERED',
                 'outcomes':{'60m':{'net_roi_pct':1.2}}})
        lab.recovery_state(b,'momentum_long',NOW+dt.timedelta(hours=53),rows)
        new=[dict(closed_loss(i),exit_at=(NOW+dt.timedelta(hours=53,minutes=i+1)).isoformat()) for i in range(3)]
        outcome=lab.recovery_state(b,'momentum_long',NOW+dt.timedelta(hours=54),rows+new)
        self.assertFalse(outcome['allowed'])
        self.assertEqual(outcome['status'],'PAUSED')

    def test_blocked_cost_candidate_appears_in_forward_audit(self):
        state,q,f=fixture()
        f['PF_TESTUSD'].update(atr=.12,ema_fast=100.05,ema_slow=99.95)
        b=st.advance(state,NOW,q,f,set(q))
        self.assertIsNone(b['position'])
        self.assertEqual(b['forward_signals'][0]['rejection_reason'],'COST_HURDLE')
        self.assertEqual(state['cash_gbp'],1988.11)

    def test_loss_paused_candidate_still_generates_recovery_shadow(self):
        state,q,f=fixture();b=st.initialize(state,NOW)
        b['closed']=[closed_loss(i) for i in range(3)]
        b=st.advance(state,NOW,q,f,set(q))
        self.assertIsNone(b['position'])
        self.assertEqual(b['forward_signals'][0]['rejection_reason'],'LOSS_SUSPENSION')
        self.assertEqual(b['recovery_v1']['momentum_long']['status'],'PAUSED')

    def test_selected_trade_exact_setup_not_other_signal(self):
        b={'version':st.VERSION}
        base={'symbol':'PF_TESTUSD','direction':1,'regime':'ACTIVE_TREND',
              'rejection_reason':'RANKED_BELOW_SELECTED'}
        cs=[dict(base,setup='momentum_long'),dict(base,setup='pump_fade')]
        lab.observe_forward(b,NOW,{'PF_TESTUSD':{'bid':99,'ask':100}},cs,('PF_TESTUSD','momentum_long'))
        self.assertEqual([r['decision'] for r in b['forward_signals']],
                         ['ENTERED','OBSERVED_NOT_ENTERED'])

if __name__=='__main__': unittest.main()
