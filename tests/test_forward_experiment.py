import copy
import datetime as dt
import unittest
from unittest.mock import patch
from agent import forward_experiment as lab
from agent import strategies
from test_strategies import fixture,NOW


def inputs():
    state,q,f=fixture()
    f['X'].update(previous_fast=100.,previous_low=99.7,previous_high=100.1,
                  previous=99.9,ema_fast=99.95)
    return state,q,f


class ForwardExperiment(unittest.TestCase):
    def test_isolation_equal_start_and_matching_costs(self):
        s,q,f=inputs();original=copy.deepcopy(s)
        t=lab.advance(s,NOW,q,f,set(q))
        for key in ('cash_gbp','positions','closed'):
            self.assertEqual(s[key],original[key])
        self.assertNotIn('strategies_v1',s['research'])
        a,b=t['arms'].values()
        self.assertEqual(a['position'],b['position'])
        self.assertEqual(a['cash_usd'],b['cash_usd'])
        self.assertFalse(t['automatic_promotion'])

    def test_chase_rejected_but_baseline_enters(self):
        s,q,f=inputs();f['X']['previous']=100.1
        t=lab.advance(s,NOW,q,f,set(q))
        self.assertIsNotNone(t['arms']['baseline']['position'])
        self.assertIsNone(t['arms']['pullback']['position'])

    def test_short_pullback_is_symmetric_and_missing_fields_fail_closed(self):
        _,q,f=inputs();x=f['X'];x.update(previous=100.1,ema_fast=100.05)
        self.assertTrue(lab.pullback_entry('momentum_short',-1,x,q['X']))
        self.assertFalse(lab.pullback_entry('pump_fade',-1,x,q['X']))
        del x['previous_fast']
        self.assertFalse(lab.pullback_entry('momentum_short',-1,x,q['X']))

    def test_no_backfill_and_duplicate_cycle_is_noop(self):
        s,q,f=inputs();t=lab.advance(s,NOW,q,f,set(q));before=copy.deepcopy(s)
        lab.advance(s,NOW,q,f,set(q));self.assertEqual(s,before)
        lab.advance(s,NOW-dt.timedelta(minutes=5),q,f,set(q));self.assertEqual(s,before)
        self.assertEqual(t['arms']['baseline']['closed'],[])

    def test_loss_budget_latches_and_does_not_reset_next_day(self):
        s,q,f=inputs();lab.advance(s,NOW,q,{},set(q))
        s['research'][lab.KEY]['arms']['pullback']['cash_usd']=1959.
        for days in (1,2):
            now=NOW+dt.timedelta(days=days)
            s['research']['news_v1']['checked_at']=now.isoformat()
            t=lab.advance(s,now,q,f,set(q))
            b=t['arms']['pullback']
            self.assertEqual(b['experiment_entry_block'],'LOSS_BUDGET_EXHAUSTED')
            self.assertIsNone(b['position'])

    def test_gap_loss_closes_at_observed_price_and_no_same_cycle_reentry(self):
        s,q,f=inputs();lab.advance(s,NOW,q,f,set(q))
        q['X'].update(bid=80,ask=80.02,mid=80.01)
        q['Y']=dict(bid=99.99,ask=100.01,mid=100,relativeFundingRate=.00001)
        f['Y']=dict(f['X'])
        t=lab.advance(s,NOW+dt.timedelta(minutes=5),q,f,set(q))
        for b in t['arms'].values():
            self.assertEqual(len(b['closed']),1)
            self.assertLess(b['closed'][0]['net_usd'],-40)
            self.assertIsNone(b['position'])
            self.assertEqual(b['experiment_entry_block'],'LOSS_BUDGET_EXHAUSTED')

    def test_missing_quote_cannot_fabricate_exit_or_flatten(self):
        s,q,f=inputs();lab.advance(s,NOW,q,f,set(q))
        t=lab.advance(s,NOW+dt.timedelta(minutes=5),{},f,set(q))
        self.assertIsNotNone(t['arms']['baseline']['position'])
        self.assertEqual(t['arms']['baseline']['closed'],[])
        self.assertEqual(t['arms']['baseline']['status'],'HOLD_UNPRICED')

    def test_source_drift_invalidates_without_reset(self):
        s,q,f=inputs();lab.advance(s,NOW,q,{},set(q))
        old=s['research'][lab.KEY]['registered_at']
        with patch.object(lab,'source_hash',return_value='changed'):
            t=lab.advance(s,NOW+dt.timedelta(minutes=5),q,f,set(q))
        self.assertEqual(t['status'],'INVALIDATED')
        self.assertEqual(t['registered_at'],old)
        self.assertIsNone(t['arms']['baseline']['position'])

    def test_invalidated_epoch_one_is_archived_once_before_separate_epoch_three(self):
        s,q,f=inputs()
        old=lab.advance(s,NOW,q,f,set(q))
        old['version']=lab.LEGACY_VERSION
        old['invalidated_at']=(NOW+dt.timedelta(minutes=1)).isoformat()
        old['invalid_reason']='ECONOMIC_SOURCE_CHANGED_NO_AUTOMATIC_RESTART'
        old['arms']['baseline']['closed']=[{
            'net_usd':-4.81776,'stress_net_usd':-8.332792,
            'opened_at':NOW.isoformat()}]
        old_summary=copy.deepcopy(old['summary'])
        old_source=old['source_sha256']
        new_time=NOW+dt.timedelta(minutes=5)
        current=lab.advance(s,new_time,q,f,set(q))
        archive=s['research'][lab.ARCHIVE_KEY]
        self.assertEqual(len(archive),1)
        self.assertEqual(archive[0]['version'],lab.LEGACY_VERSION)
        self.assertEqual(archive[0]['source_sha256'],old_source)
        self.assertEqual(archive[0]['summary'],old_summary)
        self.assertEqual(archive[0]['arms']['baseline']['closed'][0]['net_usd'],-4.81776)
        self.assertEqual(current['version'],lab.ACTIVE_VERSION)
        self.assertEqual(current['predecessor_version'],lab.PREVIOUS_VERSION)
        self.assertEqual(current['restart_reason'],
                         'SEPARATE_EPOCH_AFTER_STABLE_SCAN_ENGINEERING')
        self.assertEqual(current['arms']['baseline']['closed'],[])
        self.assertEqual(current['registered_at'],new_time.isoformat())
        lab.advance(s,new_time+dt.timedelta(minutes=5),q,f,set(q))
        self.assertEqual(len(s['research'][lab.ARCHIVE_KEY]),1)

    def test_invalidated_epoch_two_with_open_position_waits_until_flat(self):
        s,q,f=inputs()
        trial=lab.advance(s,NOW,q,f,set(q))
        trial['version']=lab.PREVIOUS_VERSION
        trial['invalidated_at']=NOW.isoformat()
        trial['invalid_reason']='HELD_CANDLE_COVERAGE_CHANGED'
        registered=trial['registered_at']
        self.assertIsNotNone(trial['arms']['baseline']['position'])
        active=lab.advance(s,NOW+dt.timedelta(minutes=5),q,f,set(q))
        self.assertEqual(active['version'],lab.PREVIOUS_VERSION)
        self.assertEqual(active['registered_at'],registered)
        self.assertNotIn(lab.ARCHIVE_KEY,s['research'])
        active['arms']['baseline']['position']=None
        active['arms']['pullback']['position']=None
        new=lab.advance(s,NOW+dt.timedelta(minutes=10),q,f,set(q))
        self.assertEqual(new['version'],lab.ACTIVE_VERSION)
        self.assertEqual(len(s['research'][lab.ARCHIVE_KEY]),1)
        self.assertEqual(s['research'][lab.ARCHIVE_KEY][0]['version'],
                         lab.PREVIOUS_VERSION)

    def test_invalidated_epoch_three_does_not_auto_restart(self):
        s,q,f=inputs()
        trial=lab.advance(s,NOW,q,f,set(q))
        trial['invalidated_at']=NOW.isoformat()
        trial['invalid_reason']='FUTURE_SOURCE_CHANGE'
        registered=trial['registered_at']
        again=lab.advance(s,NOW+dt.timedelta(minutes=5),q,f,set(q))
        self.assertEqual(again['status'],'INVALIDATED')
        self.assertEqual(again['registered_at'],registered)
        self.assertNotIn(lab.ARCHIVE_KEY,s['research'])

    def test_deadline_stops_new_entries_and_does_not_claim_validation(self):
        s,q,f=inputs();lab.advance(s,NOW,q,{},set(q))
        t=lab.advance(s,NOW+dt.timedelta(days=28),q,f,set(q))
        self.assertEqual(t['status'],'COMPLETED_NO_PROMOTION')
        self.assertIsNone(t['arms']['pullback']['position'])

    def test_failed_second_arm_does_not_commit_first_arm(self):
        s,q,f=inputs();lab.advance(s,NOW,q,{},set(q));before=copy.deepcopy(s['research'][lab.KEY])
        original=strategies.advance;calls=[]
        def fail_second(*a,**kw):
            calls.append(1)
            if len(calls)==2:raise ValueError('deliberate')
            return original(*a,**kw)
        with patch.object(strategies,'advance',side_effect=fail_second):
            self.assertIsNone(lab.safe_advance(s,NOW+dt.timedelta(minutes=5),q,f,set(q)))
        self.assertEqual(s['research'][lab.KEY],before)
        self.assertEqual(s['research']['forward_experiment_error']['type'],'ValueError')

    def test_run_reuses_market_batch_and_cannot_change_main_book(self):
        s,q,f=inputs();control=copy.deepcopy(s)
        expected=strategies.advance(control,NOW,q,f,set(q))
        with patch.object(strategies,'market',return_value=(q,f,set(q))) as market:
            actual=strategies.run(s,now=NOW)
        self.assertEqual(actual,expected)
        self.assertEqual(market.call_count,1)
        self.assertIn(lab.KEY,s['research'])
