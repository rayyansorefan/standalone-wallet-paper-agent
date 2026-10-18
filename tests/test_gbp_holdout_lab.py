"""Post-failure holdout is prospective, robust and isolated from GBP trading."""
import copy
import datetime as dt
import json
import unittest

from agent import core, dashboard
from agent import gbp_holdout_lab as lab

NOW = dt.datetime(2026, 10, 18, 19, tzinfo=dt.timezone.utc)


def row(identity="one", at=None, outcome=3., **features):
    technical = dict(change_5m_pct=.5, change_1h_pct=4.,
                     volume_pace_ratio=.8, buy_count_share=.52,
                     liquidity_usd=300000., age_hours=48.)
    technical.update(features)
    outcomes = {} if outcome is None else {
        horizon: {"net_quote_roi_pct": outcome} for horizon in lab.HORIZONS}
    return dict(signal_id=identity, token="pool-" + identity,
                at=(at or NOW).isoformat(), accepted_by_policy=True,
                signal_technical=technical, outcomes=outcomes)


class GBPPostFailureHoldout(unittest.TestCase):
    def test_rules_are_predeclared_and_missing_features_fail_closed(self):
        sample = row()
        self.assertTrue(lab.match("all_fresh_signals_control", sample))
        self.assertTrue(lab.match("tempered_continuation", sample))
        self.assertTrue(lab.match("policy_low_chase", sample))
        self.assertFalse(lab.match("mature_liquid_pullback", sample))
        sample["signal_technical"]["change_5m_pct"] = -1
        self.assertTrue(lab.match("mature_liquid_pullback", sample))
        sample["signal_technical"]["volume_pace_ratio"] = None
        self.assertIsNone(lab.match("tempered_continuation", sample))
        with self.assertRaises(ValueError):
            lab.match("unregistered", row())

    def test_registration_excludes_prior_rows_and_never_changes_accounts(self):
        old = row("old", NOW - dt.timedelta(minutes=5), 50.)
        state = core.blank_state()
        state["cash_gbp"] = 1976.52
        state["closed"] = [{"immutable": True}]
        state.setdefault("research", {})[lab.UPSTREAM_KEY] = {
            "retained_forward_signals": {"old": old}}
        preserved = copy.deepcopy({key: state[key] for key in
                                   ("cash_gbp", "positions", "closed")})
        book = lab.update(state, NOW)
        self.assertEqual(book["post_registration_observations"], 0)
        fresh = row("fresh", NOW + dt.timedelta(seconds=1), 3.)
        state["research"][lab.UPSTREAM_KEY]["retained_forward_signals"]["fresh"] = fresh
        book = lab.update(state, NOW + dt.timedelta(minutes=5))
        self.assertEqual(book["post_registration_observations"], 1)
        self.assertEqual(preserved, {key: state[key] for key in preserved})
        self.assertFalse(book["automatic_promotion"])
        self.assertFalse(book["paper_entries_allowed"])

    def test_review_gate_requires_robust_positive_holdout_and_control_edge(self):
        rows = []
        for day in range(14):
            for index in range(8):
                value = 5. if index < 6 else -3.
                rows.append(row(f"{day}-{index}", NOW + dt.timedelta(days=day,
                                minutes=index), value))
        control = lab._score(rows + [row("control-loss", NOW, -20.,
                             change_5m_pct=8.)], "5m", comparator=True)
        score = lab._score(rows, "5m", control["mean_net_quote_roi_pct"])
        self.assertEqual(score["priced"], 112)
        self.assertGreater(score["wins"], score["losses"])
        self.assertGreater(score["stressed_net_roi_points"], 0)
        self.assertGreater(score["net_without_best_observation"], 0)
        self.assertGreater(score["net_without_best_day"], 0)
        self.assertGreater(score["net_without_best_pool"], 0)
        self.assertEqual(score["review_status"], "REVIEW_ELIGIBLE_NOT_PROMOTED")
        self.assertFalse(score["paper_entry_enabled"])

    def test_persistent_negative_rule_is_rejected_but_not_traded(self):
        rows = [row(str(i), NOW + dt.timedelta(days=i % 3), -1.) for i in range(30)]
        score = lab._score(rows, "5m", 0.)
        self.assertEqual(score["review_status"], "REJECTED_PERSISTENT_NEGATIVE")
        self.assertFalse(score["paper_entry_enabled"])

    def test_source_drift_and_upstream_conflict_fail_closed_without_restart(self):
        state = {"research": {lab.UPSTREAM_KEY: {"retained_forward_signals": {}}}}
        book = lab.update(state, NOW)
        registered = book["registered_at"]
        book["hypothesis_sha256"] = "changed"
        lab.update(state, NOW + dt.timedelta(minutes=5))
        self.assertEqual(book["status"], "INVALIDATED_SOURCE_CHANGED")
        self.assertEqual(book["registered_at"], registered)
        self.assertFalse(book["paper_entries_allowed"])

        clean = {"research": {lab.UPSTREAM_KEY: {
            "retention_conflict": True, "retained_forward_signals": {}}}}
        self.assertEqual(lab.update(clean, NOW)["status"],
                         "UPSTREAM_EVIDENCE_UNSAFE")

    def test_compact_health_excludes_upstream_private_rows(self):
        state = core.blank_state()
        state.setdefault("research", {})[lab.UPSTREAM_KEY] = {
            "retained_forward_signals": {"private": row("private")}}
        lab.update(state, NOW)
        state["research"][lab.KEY]["private_rows"] = {"wallet": "SECRET"}
        published = dashboard.compact_health(state)["gbp_holdout_lab"]
        body = json.dumps(published)
        self.assertIn("GBP_ANTI_CHASE_HOLDOUT_1", body)
        self.assertNotIn("SECRET", body)
        self.assertNotIn("private_rows", published)
        self.assertFalse(published["paper_entries_allowed"])


if __name__ == "__main__":
    unittest.main()
