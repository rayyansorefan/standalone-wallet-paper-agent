import datetime as dt,tempfile,unittest
from pathlib import Path
from unittest import mock
from agent import core
from agent.safety import screen_token
from agent.dashboard import html_dashboard

class Additional(unittest.TestCase):
    def test_missing_price_makes_equity_unavailable(self):
        s=core.blank_state();s['positions']=[dict(notional_gbp=10,token='MISSING',entry_price_usd=1,wallet='OTHER',exit_at='2026-01-01T00:00:00+00:00')]
        self.assertIsNone(core.equity(s,{}))
    def test_safety_fail_closed(self):
        self.assertFalse(screen_token('invalid'))
    def test_safe_missing_data_never_opens(self):
        s=core.blank_state();t=dt.datetime.now(core.UTC)
        s['positions']=[dict(notional_gbp=10,token='MISSING',entry_price_usd=1,wallet='OTHER',exit_at='2026-01-01T00:00:00+00:00')]
        s['observed']['A'*32]={'count':3}
        core.maybe_open(s,dict(wallet='A'*32,token='TEST',id='id',timestamp=t,pool_name='TEST'),1,t,{'TEST':1})
        self.assertEqual(len(s['positions']),1)
    def test_static_report_escapes_untrusted_symbols(self):
        s=core.blank_state();s['decisions']=[dict(at=None,action='<script>alert(1)</script>',wallet=None,reason='test')]
        with tempfile.TemporaryDirectory() as d:
            p=str(Path(d)/'index.html');html_dashboard(s,p)
            h=Path(p).read_text()
            self.assertNotIn('<script>alert(1)</script>',h)
            self.assertIn('&lt;script&gt;',h)

if __name__=='__main__':unittest.main()
