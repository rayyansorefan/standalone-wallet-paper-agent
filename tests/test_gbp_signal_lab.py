"""Predeclared, no-fill prospective comparison; historical winners are never promoted."""
import copy
import datetime as dt
import json
import unittest
from unittest import mock

from agent import gbp_signal_lab as lab
from agent.decision import observe_forward
from agent.dashboard import compact_health

NOW = dt.datetime(2026, 10, 18, 15, tzinfo=dt.timezone.utc)


def tech(**kw):
    d=dict(change_5m_pct=1.5,change_1h_pct=6.,
           volume_pace_ratio=1.4,buy_count_share=.57,
           liquidity_usd=350000.,age_hours=48.,
           signal_age_seconds=45.)
    d.update(kw)
    return d


def observation(id='s1', at=NOW, f=None, outcomes=None):
    return dict(signal_id=id,token='token1',at=at.isoformat(),price=1.,
                signal_technical=tech() if f is None else f,
                accepted_by_policy=True,reasons=[],
                outcomes=outcomes if outcomes is not None else {})


class GBPResearch(unittest.TestCase):
    def test_arm_admissions_are_predeclared_and_missing_fails_closed(self):
        p=observation()
        self.assertTrue(lab.match('accelerating_breakout',p))
        self.assertTrue(lab.match('liquid_confirmed_trend',p))
        self.assertFalse(lab.match('high_volume_trend',p))
        p['signal_technical']['volume_pace_ratio']=None
        self.assertIsNone(lab.match('accelerating_breakout',p))
        p.pop('signal_technical')
        self.assertIsNone(lab.match('observed_original_gate',p))
        with self.assertRaises(ValueError):
            lab.match('not_a_registered_strategy',observation())

    def test_no_historical_backfill_and_missing_outcomes_not_fabricated(self):
        prior=observation('old',NOW-dt.timedelta(days=1),
                          outcomes={'5m':{'net_quote_roi_pct':100}})
        state={'research':{'decision_v1':{'forward_outcomes':[prior],
                                         'forward_pending':[]}},
               'closed':[], 'positions':[], 'cash_gbp':2000}
        original=copy.deepcopy(state)
        b=lab.update(state,NOW)
        self.assertEqual(b['observations'],0)
        self.assertEqual(b['status'],'COLLECTING_UNPROVEN')
        self.assertEqual(state['cash_gbp'],original['cash_gbp'])
        self.assertEqual(state['closed'],original['closed'])
        self.assertEqual(state['positions'],original['positions'])
        new=observation('fresh',NOW+dt.timedelta(seconds=1),
                        outcomes={'5m':{'net_quote_roi_pct':3.5},
                                  '30m':{'status':'MISSING_FRESH_QUOTE'}})
        state['research']['decision_v1']['forward_pending'].append(new)
        b=lab.update(state,NOW+dt.timedelta(minutes=7))
        m=b['reports']['accelerating_breakout']['horizons']
        self.assertEqual(m['5m']['priced'],1)
        self.assertEqual(m['5m']['wins'],1)
        self.assertEqual(m['30m']['missing'],1)
        self.assertEqual(m['60m']['pending'],1)
        self.assertEqual(m['5m']['mean_stressed_quote_roi_pct'],1.5)
        self.assertFalse(m['5m']['evidence_sufficient_for_review'])
        self.assertFalse(b['automatic_promotion'])

    def test_registration_version_drift_freezes_not_restarts(self):
        state={'research':{},'closed':[]}
        registered=lab.update(state,NOW)['registered_at']
        book=state['research'][lab.KEY]
        book['hypothesis_sha256']='simulated source drift'
        lab.update(state,NOW+dt.timedelta(days=1))
        self.assertEqual(book['status'],'INVALIDATED_RESEARCH_CODE_CHANGED')
        self.assertEqual(book['registered_at'],registered)
        self.assertFalse(book['automatic_promotion'])

    def test_signal_feature_snapshot_is_frozen_before_forward_marks(self):
        state={'research':{},'observed':{'w':{'count':3}}}
        assessment=dict(allowed=True,reasons=[],technical=tech())
        ev=dict(id='s1',wallet='w',token='t',kind='buy',timestamp=NOW,
                liquidity_usd=350000.,age_hours=48.)
        with mock.patch('agent.decision.entry_assessment',return_value=assessment):
            observe_forward(state,[ev],{'t':1.},NOW)
        snap=state['research']['decision_v1']['forward_pending'][0]['signal_technical']
        self.assertEqual(snap['liquidity_usd'],350000)
        self.assertEqual(snap['signal_age_seconds'],0)
        assessment['technical']['change_1h_pct']=999
        self.assertEqual(snap['change_1h_pct'],6.)

    def test_historical_legacy_winners_not_conflated_with_matching_policy(self):
        t=dict(token='poolA',exit_at=NOW.isoformat(),net_pnl_gbp=1.,
               entry_assessment={'technical':tech()})
        s={'closed':[t]*4+[dict(t,net_pnl_gbp=-1.)]*9,'research':{}}
        a=lab.update(s,NOW)['historical_audit']
        self.assertEqual(a['wins'],4)
        self.assertEqual(a['losses'],9)
        self.assertEqual(a['last_winners_distinct_pools'],1)
        self.assertEqual(a['last_winners_current_policy'],0)

    def test_compact_health_never_publishes_signal_ids_or_wallets(self):
        state={'research':{},'closed':[],'positions':[],'paper_only':True}
        lab.update(state,NOW)
        state['research'][lab.KEY]['private_wallet']='SHOULD_NOT_PUBLISH'
        content=json.dumps(compact_health(state),sort_keys=True)
        self.assertNotIn('SHOULD_NOT_PUBLISH',content)
        self.assertIn('gbp_signal_lab',content)
        self.assertIn('COLLECTING_UNPROVEN',content)


if __name__=='__main__':
    unittest.main()
