"""Tests ensure old GBP losing research samples do not vanish."""
import datetime as dt
import unittest
from agent import gbp_signal_lab as lab

NOW=dt.datetime(2026,10,18,16,tzinfo=dt.timezone.utc)

class Retention(unittest.TestCase):
    def test_rolling_buffer_does_not_erase_loss(self):
        state={'research':{'decision_v1':{'forward_outcomes':[],
                                         'forward_pending':[]}},'closed':[]}
        lab.update(state,NOW)
        item={'signal_id':'one','token':'pool',
              'at':(NOW+dt.timedelta(seconds=1)).isoformat(),
              'accepted_by_policy':True,
              'signal_technical':{'change_5m_pct':1.,
                                  'change_1h_pct':5.,
                                  'volume_pace_ratio':1.,
                                  'buy_count_share':.6},
              'outcomes':{'5m':{'net_quote_roi_pct':-3.},
                          '30m':{'status':'MISSING_FRESH_QUOTE'}}}
        state['research']['decision_v1']['forward_pending']=[item]
        lab.update(state,NOW+dt.timedelta(minutes=8))
        state['research']['decision_v1']['forward_pending']=[]
        b=lab.update(state,NOW+dt.timedelta(minutes=12))
        h=b['reports']['observed_original_gate']['horizons']
        self.assertEqual(b['observations'],1)
        self.assertEqual(h['5m']['losses'],1)
        self.assertEqual(h['30m']['missing'],1)
        self.assertFalse(b['automatic_promotion'])

    def test_duplicate_upstream_row_never_rewrites_loss_or_entry(self):
        s={'research':{'decision_v1':{'forward_outcomes':[],'forward_pending':[]}},
           'closed':[]}
        lab.update(s,NOW)
        item={'signal_id':'two','token':'pool',
              'at':(NOW+dt.timedelta(seconds=1)).isoformat(),
              'accepted_by_policy':True,
              'signal_technical':{'change_5m_pct':1.,
                                  'change_1h_pct':5.,
                                  'volume_pace_ratio':1.,
                                  'buy_count_share':.6},
              'outcomes':{'5m':{'net_quote_roi_pct':-3.}}}
        s['research']['decision_v1']['forward_outcomes']=[item,item]
        lab.update(s,NOW+dt.timedelta(minutes=8))
        item['signal_technical']['change_5m_pct']=99
        item['outcomes']['5m']['net_quote_roi_pct']=7.
        b=lab.update(s,NOW+dt.timedelta(minutes=13))
        self.assertEqual(b['observations'],1)
        saved=next(iter(b['retained_forward_signals'].values()))
        self.assertEqual(saved['signal_technical']['change_5m_pct'],1.)
        self.assertEqual(saved['outcomes']['5m']['net_quote_roi_pct'],-3.)

if __name__=='__main__':
    unittest.main()
