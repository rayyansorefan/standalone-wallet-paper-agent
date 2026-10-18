"""Regression checks for non-trading RSI/EMA/MACD quote research."""
import copy
import datetime as dt
import unittest

from agent import gbp_quote_ta as ta

NOW = dt.datetime(2026, 10, 18, 12, tzinfo=dt.timezone.utc)


class TechnicalLab(unittest.TestCase):
    def test_requires_35_real_contiguous_observations(self):
        s = {"cash_gbp": 1234., "positions": [{"old": True}], "closed": [{"old": True}], "research": {}}
        preserved = copy.deepcopy({k:s[k] for k in ("cash_gbp","positions","closed")})
        for i in range(34):
            at = NOW + dt.timedelta(minutes=5*i)
            ta.update(s, {"poolA": 1 + i * .001}, at)
        b = s["research"][ta.KEY]
        self.assertEqual(len(b["pending"]), 0)
        ta.update(s, {"poolA": 1.034}, NOW+dt.timedelta(minutes=170))
        self.assertEqual(len(b["pending"]), 1)
        self.assertEqual(b["pending"][0]["arms"][0], "sampled_quote_control")
        self.assertEqual(b["pending"][0]["features"]["marks"], 35)
        self.assertEqual(preserved, {k:s[k] for k in preserved})
        self.assertFalse(b["automatic_promotion"])
        self.assertFalse(b["paper_entries_allowed"])

    def test_real_quote_outcome_net_of_two_sided_cost_and_gap_is_missing(self):
        s = {"research":{}}
        for i in range(35):
            ta.update(s, {"p":1. + .001*i}, NOW+dt.timedelta(minutes=5*i))
        b = s["research"][ta.KEY]
        row = b["pending"][0]
        ta.update(s, {"p":row["entry_price"]*1.05},
                  NOW+dt.timedelta(minutes=175))
        self.assertAlmostEqual(row["outcomes"]["5m"]["net_quote_roi_pct"],
                               100*(1.05*.99/1.01 - 1),places=4)
        self.assertNotIn("30m",row["outcomes"])
        ta.update(s, {}, NOW+dt.timedelta(minutes=220))
        self.assertEqual(row["outcomes"]["30m"]["status"],"MISSING_FRESH_MARK")
        self.assertEqual(row["outcomes"]["60m"]["status"],"MISSING_FRESH_MARK")
        self.assertEqual(b["reports"]["sampled_quote_control"]["30m"]["missing"],1)

    def test_gap_invalidates_technical_contiguity(self):
        s = {}
        for i in range(34):
            ta.update(s, {"p":1+i*.001}, NOW+dt.timedelta(minutes=5*i))
        ta.update(s, {"p":2.}, NOW+dt.timedelta(minutes=5*34+15))
        book = s["research"][ta.KEY]
        self.assertEqual(len(book["marks"]["p"]),1)
        self.assertEqual(book["reset_gaps"],1)
        self.assertEqual(len(book["pending"]),0)

    def test_same_slot_not_multiple_ticks_or_fabricated_evidence(self):
        s={}
        ta.update(s, {"p":1.},NOW)
        ta.update(s, {"p":1.1},NOW+dt.timedelta(seconds=10))
        self.assertEqual(len(s["research"][ta.KEY]["marks"]["p"]),1)
        self.assertEqual(s["research"][ta.KEY]["total_marks"],1)
        ta.update(s, {"p":1.2},NOW+dt.timedelta(minutes=5))
        self.assertEqual(len(s["research"][ta.KEY]["marks"]["p"]),2)

    def test_known_patterns_are_shadow_only(self):
        f=dict(close=101,ema12=100,ema26=99,macd=1,macd_signal9=.5,
               rsi14=60,change_5m_pct=1,previous_20_mark_high=100)
        self.assertEqual(ta.select_arms(f),[
            "sampled_quote_control","ema_macd_continuation","observed_high_breakout"])
        f.update(close=97,ema12=98,ema26=99,macd=-1,macd_signal9=-.5,
                 rsi14=30,change_5m_pct=-1)
        self.assertEqual(ta.select_arms(f),
                         ["sampled_quote_control","oversold_reversion"])

    def test_source_drift_fails_closed_without_resetting_history(self):
        s={}
        b=ta.update(s,{"p":1},NOW)
        registered=b["registered_at"]
        b["hypothesis_sha256"]="modified"
        ta.update(s,{"p":2},NOW+dt.timedelta(minutes=5))
        self.assertEqual(b["status"],"INVALIDATED_SOURCE_CHANGED")
        self.assertEqual(b["registered_at"],registered)
        self.assertEqual(len(b["marks"]["p"]),1)

    def test_missing_prices_and_nonfinite_inputs_not_marks(self):
        s={}
        ta.update(s,{"p":float("nan"),"q":-1,"r":0,"ok":1},NOW)
        self.assertEqual(set(s["research"][ta.KEY]["marks"]),{"ok"})

    def test_finite_state_and_bounded_memory(self):
        s={}
        for i in range(35):
            quotes={str(j):1+i*.001 for j in range(110)}
            ta.update(s,quotes,NOW+dt.timedelta(minutes=5*i))
        b=s["research"][ta.KEY]
        self.assertLessEqual(len(b["marks"]),ta.MAX_SERIES)
        self.assertLessEqual(len(b["pending"]),ta.MAX_PENDING)
        self.assertLessEqual(len(b["done"]),ta.MAX_DONE)


if __name__ == "__main__":
    unittest.main()
