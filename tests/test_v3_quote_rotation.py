"""Regression tests for V3 supplemental-quote absence and forward-only rotation.

Research-only tests: they never run a real order, create an account, or raise
existing request/risk budgets. Run from the upstream repository's root.
"""
import copy
import datetime as dt
import unittest
from unittest.mock import patch

from agent import core, whales

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 16, 16, 0, tzinfo=UTC)


def pool(addr, price=1.0):
    return dict(pool=addr, mint='A' * 32, name=addr + '/SOL',
                price_usd=price, liquidity_usd=500_000,
                volume_24h_usd=600_000, age_hours=48,
                change_24h_pct=5.0)


def state():
    s = dict(paper_only=True, starting_gbp=2000., cash_gbp=1975.,
             last_run=(NOW - dt.timedelta(minutes=5)).isoformat(),
             completed_cycles=1, watched_pools=[], positions=[{'token':'original','wallet':'w'}],
             closed=[{'wallet':'prior','net_pnl_gbp':-0.5}])
    r = whales.initialize(s)
    # Four eligible supplemental candidates; only two are examined in a cycle.
    r['pool_registry'] = {addr:pool(addr) for addr in ('P1', 'P2', 'P3', 'P4')}
    r['watched_pools'] = [pool('P1'), pool('P2')]
    return s


class QuoteRotation(unittest.TestCase):
    def setUp(self):
        self.s = state()
        self.protected = {k:copy.deepcopy(self.s[k]) for k in
                          ('paper_only','starting_gbp','cash_gbp','positions','closed')}
        self.core_patches = [
            patch.object(core, 'eligible', side_effect=lambda m:m.get('price_usd',0)>0 and m.get('liquidity_usd',0)>=100_000),
            patch.object(core, 'pool_meta', side_effect=lambda raw:copy.deepcopy(raw['meta'])),
            patch.object(core, 'extract_event', return_value=None),
        ]
        for p in self.core_patches:
            p.start()
            self.addCleanup(p.stop)

    def run_research(self, quoted=('P2',), current=NOW, core_candidates=()):
        calls=[]
        def fetch(path, params=None):
            calls.append(path)
            if 'trending_pools' in path:
                raise AssertionError('No discovery request due in this cycle')
            if '/multi/' in path:
                return {'data':[{'meta':pool(x)} for x in quoted]}
            if path.endswith('/trades'):
                return {'data':[]}
            raise AssertionError('Unexpected research request: ' + path)
        result=whales.whale_cycle(self.s, list(core_candidates), [], {}, current,
                                  fetch=fetch, screener=lambda _:True,
                                  previous_run=current-dt.timedelta(minutes=5), discovered=[])
        return result,calls

    def test_missing_quote_marks_attempted_and_rotates_next_cycle(self):
        r,calls=self.run_research()
        self.assertEqual(r['status'],'DEGRADED')
        self.assertEqual(set(r['last_quotes']),{'P2'})
        self.assertTrue(any('fresh supplemental quote missing for P1' in e for e in r['last_scan_errors']))
        self.assertEqual(r['pool_last_scanned']['P1'],NOW.isoformat(timespec='seconds'))
        self.assertEqual(r['scan_metrics']['trade_feeds'],1)
        self.assertEqual(len([p for p in calls if p.endswith('/trades')]),1)
        self.s['completed_cycles']=2
        whales._pick_watchlist(self.s, lambda *a: (_ for _ in ()).throw(AssertionError('not due')),
                               r,discovered=[])
        self.assertEqual([p['pool'] for p in r['watched_pools']],['P3','P4'])

    def test_no_quote_does_not_scan_trades_or_pretend_healthy(self):
        r,calls=self.run_research(quoted=())
        self.assertEqual(r['scan_metrics']['trade_feeds'],0)
        self.assertEqual(r['last_quotes'],{})
        self.assertEqual(r['status'],'DEGRADED')
        self.assertFalse(any('/trades' in path for path in calls))

    def test_historically_eligible_meta_does_not_authorize_unquoted_trades(self):
        # Mimic current-cycle core metadata accidentally containing a watched pool,
        # independently of the saved primary pool list. No supplemental quote: no scan.
        r,calls=self.run_research(quoted=(), core_candidates=[pool('P1')])
        self.assertEqual(r['status'],'DEGRADED')
        self.assertEqual(r['scan_metrics']['trade_feeds'],0)
        self.assertFalse(any('/trades' in p for p in calls))

    def test_two_fresh_quotes_are_scanned_without_extra_requests(self):
        r,calls=self.run_research(quoted=('P1','P2'))
        self.assertEqual(r['status'],'OK')
        self.assertEqual(r['scan_metrics']['trade_feeds'],2)
        self.assertEqual(len([p for p in calls if p.endswith('/trades')]),2)
        self.assertEqual(len(calls),3)  # one quote request, two separate trade reads

    def test_original_account_and_trade_history_are_unchanged(self):
        self.run_research(quoted=('P1','P2'))
        for field, before in self.protected.items():
            self.assertEqual(self.s[field],before,field)


if __name__=='__main__':
    unittest.main()
