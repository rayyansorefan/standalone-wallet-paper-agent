"""Retirement is evidence-based, shadow-only, and irreversible without review."""
import datetime as dt
import copy
import unittest

from agent.shadow_retirement import retirement_check, update_retirements
from agent import adaptive, whales

NOW=dt.datetime(2026,10,17,12,0,tzinfo=dt.timezone.utc)


def negative_closes(strategy='quality'):
    rows=[]
    for i in range(30):
        ts=(NOW-dt.timedelta(days=i%8)).isoformat()
        rows.append({'strategy':strategy,'wallet':'wallet'+str(i%5),
                     'token':'pool'+str(i%4),'signal_id':'unique'+str(i),
                     'exit_at':ts, 'net_pnl_gbp':1.0 if i%6==0 else -2.0,
                     'roi_pct':10 if i%6==0 else -20,
                     'entry_price_usd':100.,'exit_price_usd':110. if i%6==0 else 80.,
                     'notional_gbp':10.,
                     'signal_features':{'mint':'mint'+str(i%4)}})
    return rows


class ConservativeRetirement(unittest.TestCase):
    def test_retirement_only_from_persistent_diverse_negative_closes(self):
        report=adaptive.pnl_report(negative_closes())
        enabled,reason=retirement_check(report)
        self.assertTrue(enabled)
        self.assertEqual(reason,'PERSISTENT_NEGATIVE_FORWARD_SHADOW_OUTCOMES')
        self.assertGreaterEqual(report['distinct_exit_days'],7)
        self.assertLess(report['profit_factor'],.7)

    def test_no_retirement_for_low_sample_or_undiversified(self):
        small=adaptive.pnl_report(negative_closes()[:10])
        self.assertFalse(retirement_check(small)[0])
        stale=negative_closes()
        for x in stale:x['wallet']='one'
        self.assertFalse(retirement_check(adaptive.pnl_report(stale))[0])

    def test_no_retirement_for_profitable_or_inconclusive(self):
        report=adaptive.pnl_report(negative_closes())
        report.update(net_gbp=1.0,profit_factor=1.5,wins=20)
        self.assertFalse(retirement_check(report)[0])

    def test_retirement_keeps_auditable_history_and_is_monotone(self):
        r={'shadow_closed':negative_closes(),'events':[]}
        report=adaptive.pnl_report(r['shadow_closed'])
        out={'quality':report}
        update_retirements(r,out,NOW)
        self.assertEqual(out['quality']['status'],'RETIRED_NEGATIVE_EVIDENCE')
        self.assertEqual(len(r['shadow_closed']),30)
        self.assertEqual(len(r['events']),1)
        replacement={'quality':dict(report,net_gbp=10.,profit_factor=4.,wins=30)}
        update_retirements(r,replacement,NOW+dt.timedelta(days=10))
        self.assertEqual(replacement['quality']['status'],'RETIRED_NEGATIVE_EVIDENCE')
        self.assertEqual(len(r['events']),1)

    def test_v2_shadow_retired_in_cycle_no_original_wallet_mutation(self):
        state={'cash_gbp':1911,'positions':[{'current':True}],'closed':[{'original':True}],
               'research':{'shadow_closed':negative_closes('quality'),'shadow_positions':[]}}
        original=copy.deepcopy({k:state[k] for k in ('cash_gbp','positions','closed')})
        r=adaptive.research_cycle(state,[],{},[],NOW)
        self.assertIn('quality',r['retired_shadow_strategies'])
        for k,v in original.items():self.assertEqual(state[k],v)
        self.assertEqual(len(r['shadow_closed']),30)

    def test_v3_retired_shadow_has_zero_new_allocation_and_keeps_closes(self):
        state={'cash_gbp':1911,'positions':[{'current':True}],'closed':[{'original':True}]}
        r=whales.initialize(state)
        r['shadow_closed']=negative_closes('accumulation')
        r['shadow_positions']=[]
        whales._update_reports(r,NOW)
        self.assertIn('accumulation',r['retired_shadow_strategies'])
        self.assertEqual(r['shadow_sizing']['accumulation'],0)
        self.assertEqual(r['shadow_reports']['accumulation']['status'],'RETIRED_NEGATIVE_EVIDENCE')
        self.assertEqual(len(r['shadow_closed']),30)
        self.assertEqual(state['cash_gbp'],1911)
        whales._update_reports(r,NOW+dt.timedelta(minutes=5))
        self.assertEqual(r['shadow_sizing']['accumulation'],0)

if __name__=='__main__':unittest.main()
