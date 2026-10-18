import copy
import json
import unittest
from agent.profitability import diagnostic,decompose
from agent.policy_evidence import new_entry_tags,new_exit_tags


def trade():
    return dict(notional_gbp=10,entry_price_usd=100,exit_price_usd=101,
                cost_gbp=10.1,proceeds_gbp=9.999,net_pnl_gbp=-.101,
                exit_reason='observed trader sell',wallet='do-not-publish',
                **new_entry_tags(),**new_exit_tags())


class ProfitabilityDiagnostics(unittest.TestCase):
    def test_gross_win_erased_by_costs_reconciles(self):
        d=decompose(trade());self.assertAlmostEqual(d['gross'],.1)
        self.assertAlmostEqual(d['drag'],.201)
        self.assertAlmostEqual(d['gross']-d['drag'],d['net'])
        self.assertTrue(d['cost_flipped'])

    def test_epochs_stay_separate_and_input_unchanged(self):
        t=trade();old=dict(t);old.pop('policy_epoch');rows=[t,old];before=copy.deepcopy(rows)
        report=diagnostic(rows)
        for c in report['cohorts'].values():
            self.assertEqual(c['closed'],1);self.assertEqual(c['decomposed_net_pnl_gbp'],-.101)
        self.assertNotIn('do-not-publish',json.dumps(report))
        self.assertEqual(rows,before)

    def test_missing_inconsistent_nonfinite_not_zero(self):
        for change in ({'entry_price_usd':None},{'net_pnl_gbp':3},{'cost_gbp':float('nan')},{'entry_price_usd':0}):
            t=trade();t.update(change);self.assertIsNone(decompose(t))
            c=diagnostic([t])['cohorts']['current_matching_policy']
            self.assertEqual(c['unknown_or_inconsistent'],1)
            self.assertIsNone(c['gross_price_pnl_gbp'])

    def test_weighted_added_position_decomposes_using_total_notional(self):
        t=trade();t.update(notional_gbp=15,entry_price_usd=105,exit_price_usd=110,
                          cost_gbp=15.15,proceeds_gbp=15.5571,net_pnl_gbp=.4071)
        d=decompose(t);self.assertAlmostEqual(d['gross']-d['drag'],.4071,places=6)

    def test_unknown_exit_text_is_not_public_and_no_closes_is_unknown(self):
        t=trade();t['exit_reason']='private-string'
        self.assertNotIn('private-string',json.dumps(diagnostic([t])))
        self.assertIsNone(diagnostic([])['cohorts']['current_matching_policy']['decomposed_net_pnl_gbp'])
