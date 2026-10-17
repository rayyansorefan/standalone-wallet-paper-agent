"""Regression tests for V4 in the existing repository."""
import datetime as dt
import unittest
from agent import strategies as s

NOW=dt.datetime(2026,10,17,10,0,tzinfo=s.UTC)


def fixture():
    state={'paper_only':True,'cash_gbp':1988.11,'positions':[], 'closed':[],
           'research':{'news_v1':{'checked_at':NOW.isoformat(),
                       'sources':{'coindesk':{'status':'OK'}}, 'risk_off':False}}}
    quotes={'PF_TESTUSD':{'bid':99.99,'ask':100.01,'mid':100.,'relativeFundingRate':.00001}}
    features={'PF_TESTUSD':dict(close=100,previous=99.9,atr=.3,
              ema_fast=99.9,ema_slow=99.5,r1h=.02,r15m=.004,
              volume_ratio=1.5,fade_volume_ratio=1,pump=.01,
              drawdown=0,peak_age=0,lower_closes=False)}
    return state,quotes,features


class Integration(unittest.TestCase):
    def test_upgrade_preserves_original_and_versioned_challenger_records(self):
        state,q,f=fixture()
        b=s.initialize(state,NOW-dt.timedelta(days=2))
        b['version']='momentum-fade-1'  # simulate the persisted legacy ledger
        b['closed'].append({'setup':'momentum_long','symbol':'PF_TESTUSD',
                            'version':'momentum-fade-1',
                            'exit_at':(NOW-dt.timedelta(days=1)).isoformat(),
                            'net_usd':-1,'risk_usd':5,'stress_net_usd':-2})
        before={'cash_gbp':state['cash_gbp'],'positions':state['positions'][:],
                'closed':state['closed'][:]}
        s.advance(state,NOW,q,f,set(q))
        self.assertEqual(b['version'],'momentum-fade-2')
        self.assertEqual(len(b['closed']),1)
        self.assertEqual(s.feedback(b,'momentum_long','PF_TESTUSD',NOW)['closed'],0)
        self.assertEqual(b['policy_registered_at'],NOW.isoformat())
        for k,v in before.items():self.assertEqual(state[k],v)
        self.assertEqual(len(b['forward_signals']),1)

    def test_vetoed_candidates_still_get_forward_learning(self):
        state,q,f=fixture()
        state['research']['news_v1']['risk_off']=True
        b=s.advance(state,NOW,q,f,set(q))
        self.assertIsNone(b['position'])
        self.assertEqual(len(b['forward_signals']),1)
        self.assertEqual(b['forward_signals'][0]['decision'],'OBSERVED_NOT_ENTERED')
        q['PF_TESTUSD'].update(bid=100.99,ask=101.01,mid=101.)
        s.advance(state,NOW+dt.timedelta(minutes=5),q,f,set(q))
        self.assertIn('5m',b['forward_signals'][0]['outcomes'])

    def test_low_volatility_cost_hurdle_blocks_new_entries(self):
        state,q,f=fixture()
        f['PF_TESTUSD']['atr']=.03
        b=s.advance(state,NOW,q,f,set(q))
        self.assertIsNone(b['position'])
        self.assertEqual(b['cost_hurdle_rejections'],1)

    def test_winner_profit_lock_tightens_before_full_1r_exit(self):
        state,q,f=fixture()
        b=s.advance(state,NOW,q,f,set(q))
        p=b['position'];self.assertIsNotNone(p)
        original_stop=p['stop']
        q['PF_TESTUSD'].update(bid=101.29,ask=101.31,mid=101.30)
        s.advance(state,NOW+dt.timedelta(minutes=5),q,f,set(q))
        self.assertGreaterEqual(p['stop'],original_stop)
        self.assertTrue(any(e['action']=='PROFIT_STOP_RATCHET' for e in b['events']))

if __name__=='__main__':unittest.main()
