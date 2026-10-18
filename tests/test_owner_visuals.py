import datetime as dt
import unittest
from pathlib import Path
from agent.position_management import observe, MAX_POSITION_HISTORY

class OwnerVisuals(unittest.TestCase):
    def test_history_is_bounded_and_real(self):
        pos={'entry_price_usd':1.0,'notional_gbp':10.0,'cost_gbp':10.1,'recent_marks':[]}
        start=dt.datetime(2026,10,18,tzinfo=dt.timezone.utc)
        for i in range(105):
            observe(pos,1.0+i/1000,start+dt.timedelta(minutes=5*i))
        self.assertEqual(len(pos['mark_history']),MAX_POSITION_HISTORY)
        self.assertEqual(len(pos['recent_marks']),3)
        observe(pos,1.2,start+dt.timedelta(minutes=520))
        self.assertEqual(len(pos['mark_history']),MAX_POSITION_HISTORY)
    def test_visual_markup(self):
        base=Path(__file__).resolve().parents[1]/'docs'
        html=(base/'index.html').read_text()
        js=(base/'owner-visuals.js').read_text()
        self.assertIn('id="owner-open-list"',html)
        self.assertIn('id="owner-position-history"',html)
        self.assertIn('id="owner-equity"',html)
        self.assertIn('window.ownerVisualRender?.(s)',html)
        self.assertIn('mark_history',js)
        self.assertIn('UNPRICED',js)
        self.assertLess(html.index('id="owner-open-positions"'),html.index('id="advanced-dashboard"'))
