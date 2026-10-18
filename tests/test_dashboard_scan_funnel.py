from pathlib import Path
import unittest


class DashboardScanFunnelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("docs/index.html").read_text(encoding="utf8")

    def test_plain_english_scan_funnel_is_visible(self):
        for element_id in (
            "scan-rows",
            "scan-assessed",
            "scan-safe",
            "scan-feeds",
            "scan-qualified",
            "scan-explain",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("What the engine scanned this cycle", self.html)

    def test_scan_funnel_uses_precise_health_metrics(self):
        for field in (
            "discovery_search_rows_examined",
            "technical_candidates_assessed",
            "security_screened",
            "trade_feeds_sampled",
            "technical_candidates_qualified",
        ):
            self.assertIn(field, self.html)
        self.assertIn("broad rows were cheap discovery leads, not full analyses", self.html)
        self.assertIn("No trade is implied by being scanned", self.html)


if __name__ == "__main__":
    unittest.main()
