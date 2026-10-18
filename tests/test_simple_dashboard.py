"""Owner dashboard stays small while retaining the complete audit below."""
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / 'docs' / 'index.html').read_text(encoding='utf8')


class SimpleDashboard(unittest.TestCase):
    def test_owner_summary_is_visible_before_collapsed_legacy(self):
        self.assertIn('<section id="simple-overview"', HTML)
        self.assertIn('<details class="legacy-dashboard" id="advanced-dashboard">', HTML)
        self.assertLess(HTML.index('id="simple-overview"'), HTML.index('id="advanced-dashboard"'))
        self.assertNotIn('<details class="legacy-dashboard" id="advanced-dashboard" open', HTML)
        self.assertIn('id="trade-history"', HTML)
        self.assertIn('id="research-details"', HTML)

    def test_coverage_metrics_are_honest_and_no_missing_source_assumed_zero(self):
        for field in ('technical_candidates_assessed', 'technical_candidates_qualified',
                      'security_screened', 'trade_feeds_sampled', 'discovery_coverage_target',
                      'deep_candle_scans', 'last_run', 'errors_this_cycle'):
            self.assertIn(field, HTML)
        for field in ('simple-assessed', 'simple-qualified', 'simple-screened', 'simple-deep',
                      'simple-gbp-pnl', 'simple-usd-pnl', 'simple-recent', 'simple-health'):
            self.assertIn('id="'+field+'"', HTML)
        self.assertIn("n(x)===null?'—'", HTML)
        self.assertIn('being assessed does NOT mean fully analysed', HTML)

    def test_single_valid_html_document_and_no_state_writes(self):
        self.assertEqual(HTML.count('<!doctype html>'), 1)
        self.assertEqual(HTML.count('</body></html>'), 1)
        self.assertEqual(HTML.count('function simpleOverview(s)'), 1)
        self.assertIn('simpleOverview(s);', HTML)
        self.assertIn("fetch('./state.json?stamp='", HTML)
        self.assertNotIn('fetch(\'/api/order', HTML)


if __name__ == '__main__':
    unittest.main()
