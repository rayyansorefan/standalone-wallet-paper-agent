import datetime as dt
import unittest
from agent import strategy_lab as v4

UTC=dt.timezone.utc
NOW=dt.datetime(2026,10,17,8,0,tzinfo=UTC)


def candidate():
    return {'symbol':'PF_TESTUSD','setup':'momentum_long','direction':1,
            'regime':'ACTIVE_TREND','score':5}


class V4ForwardLearning(unittest.TestCase):
    def test_quoted_returns_include_spread_slippage_and_fees(self):
        entry=101*(1+v4.SLIP)
        roi=v4.observed_net_roi(1,entry,{'bid':99,'ask':101})
        self.assertLess(roi,-2)
        self.assertIsNone(v4.observed_net_roi(1,entry,{'bid':None,'ask':101}))
        short=v4.observed_net_roi(-1,99*(1-v4.SLIP),{'bid':99,'ask':101})
        self.assertLess(short,-2)

    def test_cost_room_filter(self):
        f={'atr':.3,'close':100}
        q={'bid':99.99,'ask':100.01,'mid':100}
        self.assertTrue(v4.has_cost_room(f,q))
        self.assertFalse(v4.has_cost_room({'atr':.03,'close':100},q))

    def test_forward_quotes_only_and_deduplicated(self):
        b={'version':'momentum-fade-2'};q={'PF_TESTUSD':{'bid':99,'ask':101}}
        v4.observe_forward(b,NOW,q,[candidate()],('PF_TESTUSD','momentum_long'))
        self.assertEqual(len(b['forward_signals']),1)
        self.assertEqual(b['forward_signals'][0]['outcomes'],{})
        self.assertEqual(b['forward_signals'][0]['decision'],'ENTERED')
        v4.observe_forward(b,NOW+dt.timedelta(minutes=5),q,[candidate()])
        self.assertEqual(len(b['forward_signals']),1)
        self.assertLess(b['forward_signals'][0]['outcomes']['5m']['net_roi_pct'],0)
        v4.observe_forward(b,NOW+dt.timedelta(minutes=60),q,[])
        self.assertIn('60m',b['forward_signals'][0]['outcomes'])

    def test_missing_quote_not_a_zero_or_fabricated_win(self):
        b={'version':'momentum-fade-2'}
        v4.observe_forward(b,NOW,{'PF_TESTUSD':{'bid':99,'ask':101}},[candidate()])
        v4.observe_forward(b,NOW+dt.timedelta(minutes=72),{},[])
        self.assertEqual(b['forward_signals'][0]['outcomes']['60m']['status'],'MISSING_QUOTE')
        self.assertEqual(b['forward_summary']['60m']['priced'],0)

    def test_learning_requires_forward_evidence_and_multiple_days(self):
        b={'version':'momentum-fade-2','forward_signals':[]}
        for i in range(21):
            r={'at':(NOW+dt.timedelta(days=i)).isoformat(),'setup':'momentum_long',
               'regime':'ACTIVE_TREND','rule_version':'momentum-fade-2',
               'outcomes':{'60m':{'net_roi_pct':-1.8}}}
            b['forward_signals'].append(r)
        n=v4.context_adjustment(b,'momentum_long','ACTIVE_TREND')
        self.assertEqual(n['status'],'NEGATIVE_FORWARD')
        self.assertEqual(n['adjustment'],-1)
        for r in b['forward_signals']:r['outcomes']['60m']['net_roi_pct']=1.2
        p=v4.context_adjustment(b,'momentum_long','ACTIVE_TREND')
        self.assertEqual(p['status'],'POSITIVE_FORWARD')
        self.assertEqual(p['adjustment'],.5)
        b['version']='momentum-fade-3'
        self.assertEqual(v4.context_adjustment(b,'momentum_long','ACTIVE_TREND')['status'],'COLLECTING')

    def test_long_stop_locks_net_not_gross_and_never_moves_backwards(self):
        p=dict(direction=1,entry=100,units=5,entry_fees=.25,carry_usd=.05,
               risk_usd=5,best=103,stop=98)
        stop=v4.improved_stop(p,{'mid':103,'bid':102.99,'ask':103.01},8,.3)
        self.assertGreater(stop,100)
        self.assertLess(stop,103)
        q={'bid':stop,'ask':stop}
        roi=v4.observed_net_roi(1,p['entry'],q)
        self.assertGreater(roi,0)
        p['stop']=stop
        self.assertIsNone(v4.improved_stop(p,{'mid':103,'bid':102.99,'ask':103.01},2,.3))

    def test_short_stop_profit_and_no_lock_when_losing(self):
        p=dict(direction=-1,entry=100,units=5,entry_fees=.25,carry_usd=.05,
               risk_usd=5,best=97,stop=102)
        stop=v4.improved_stop(p,{'mid':97,'bid':96.99,'ask':97.01},8,.3)
        self.assertLess(stop,100)
        self.assertGreater(stop,97)
        self.assertIsNone(v4.improved_stop(p,{'mid':99,'bid':98.99,'ask':99.01},-2,.3))

    def test_no_false_signal_promotion_from_same_day(self):
        b={'version':'momentum-fade-2','forward_signals':[]}
        for i in range(40):
            b['forward_signals'].append({'at':(NOW+dt.timedelta(minutes=i*65)).isoformat(),
               'setup':'momentum_long','regime':'ACTIVE_TREND','rule_version':'momentum-fade-2',
               'outcomes':{'60m':{'net_roi_pct':2.0}}})
        self.assertEqual(v4.context_adjustment(b,'momentum_long','ACTIVE_TREND')['status'],'COLLECTING')

if __name__=='__main__':unittest.main()
