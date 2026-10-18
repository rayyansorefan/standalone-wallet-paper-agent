"""Regression tests: research-only tournament never creates trades or resets paper ledgers."""
import copy
import datetime as dt
import unittest
from research.strategy_tournament import STYLES, analyze, eligible, evaluate

START = dt.datetime(2026, 10, 18, 11, tzinfo=dt.timezone.utc)

def point(minute, price=100, safety='PASS', pool='TEST_POOL', **kwargs):
    p = dict(at=(START + dt.timedelta(minutes=minute)).isoformat(),
             pool=pool, price_usd=price, token_safety=safety,
             change_5m_pct=1, change_1h_pct=4, liquidity_usd=500000,
             volume_24h_usd=240000, volume_1h_usd=20000,
             buys_1h=70, sells_1h=30)
    p.update(kwargs)
    return p

class StrategyTournament(unittest.TestCase):
    def test_exact_two_sided_costs_and_no_orders(self):
        result = evaluate([point(0), point(5)], 'positive_momentum', 5)
        self.assertEqual(result['evaluated_quotes'], 1)
        self.assertAlmostEqual(result['avg_net_quote_roi_pct'], -1.9802, places=4)
        self.assertEqual(result['paper_orders'], 0)
        self.assertFalse(result['strategy_promotion'])

    def test_future_quote_must_be_later_within_gap(self):
        result = evaluate([point(0), point(4, 110), point(13, 150)],
                          'screened_quote_baseline', 5)
        self.assertEqual(result['evaluated_quotes'], 0)
        self.assertEqual(result['missing_future_quotes'], 1)

    def test_unsafe_or_unknown_security_never_entered(self):
        for label in ('NOT_PASS', 'UNAVAILABLE', 'FAIL', None):
            with self.subTest(label=label):
                result = evaluate([point(0, safety=label), point(5)],
                                  'screened_quote_baseline', 5)
                self.assertEqual(result['evaluated_quotes'], 0)
        self.assertFalse(eligible(point(0, safety='UNKNOWN'),
                                  'bespoke_flow_reclaim_v0_SHADOW_ONLY'))

    def test_quote_loss_not_relabelled_a_win(self):
        out = evaluate([point(0), point(5, 90)], 'screened_quote_baseline', 5)
        self.assertEqual(out['positive_net_quotes'], 0)
        self.assertLess(out['avg_net_quote_roi_pct'], -10)

    def test_bespoke_requires_buys_volume_liquidity_and_trend(self):
        rule = 'bespoke_flow_reclaim_v0_SHADOW_ONLY'
        self.assertTrue(eligible(point(0), rule))
        self.assertFalse(eligible(point(0, buys_1h=40, sells_1h=60), rule))
        self.assertFalse(eligible(point(0, liquidity_usd=10), rule))
        self.assertFalse(eligible(point(0, volume_1h_usd=100), rule))
        self.assertFalse(eligible(point(0, change_5m_pct=5), rule))

    def test_no_overlapping_per_pool_60_minute_decisions(self):
        rows = [point(t, 100+t/10) for t in range(0, 90, 5)]
        out = evaluate(rows, 'screened_quote_baseline', 5)
        self.assertEqual(out['evaluated_quotes'], 2)

    def test_missing_outcome_never_counted_as_zero(self):
        out = evaluate([point(0)], 'screened_quote_baseline', 5)
        self.assertEqual(out['evaluated_quotes'], 0)
        self.assertEqual(out['missing_future_quotes'], 1)
        self.assertIsNone(out['avg_net_quote_roi_pct'])

    def test_analysis_is_read_only_and_does_not_replace_ledgers(self):
        state = dict(research={'pool_observations':[point(0),point(5)]},
                     closed=[dict(exit_at='2026-10-18T12:00:00Z',net_pnl_gbp=1.2)],
                     positions=[{'original':'preserved'}], cash_gbp=1800,
                     starting_gbp=2000)
        initial=copy.deepcopy(state)
        report=analyze(state)
        self.assertEqual(state, initial)
        self.assertEqual(len(report['results']), len(STYLES)*3)
        self.assertEqual(report['status'], 'RESEARCH_ONLY_NO_PROMOTION')
        self.assertFalse(report['independent_forward_validation'])
        self.assertEqual(report['recent_winner_context']['count'], 1)

if __name__ == '__main__':
    unittest.main()
