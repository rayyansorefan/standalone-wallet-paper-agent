"""V3 provider-circuit regression tests. All transports mocked; no live orders."""
import copy
import datetime as dt
import io
import sys
import types
import unittest
import urllib.error
from unittest.mock import patch

from agent import research_feed

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 16, 15, 0, tzinfo=UTC)
BAD = '/networks/solana/pools/bad/trades'
GOOD = '/networks/solana/pools/good/trades'
THIRD = '/networks/solana/pools/third/trades'


class Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class PoolTimeoutIsolation(unittest.TestCase):
    def setUp(self):
        # In production, the actual agent.whales module supplies fast_fetch.
        # This stub only lets these offline provider tests run independently.
        fake_whales = types.ModuleType('agent.whales')
        fake_whales.fast_fetch = lambda *args, **kwargs: self.fail('Unexpected HTTP call')
        self.module_patch = patch.dict(sys.modules, {'agent.whales': fake_whales})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)

    def feed(self, transport, *, state=None, when=NOW):
        state = state if state is not None else {}
        state.setdefault('scan_metrics', {})
        clock = Clock()
        return research_feed.ResearchFeed(
            state, when, transport=transport, clock=clock, sleep=clock.sleep)

    def test_single_pool_read_timeout_does_not_block_other_pool(self):
        calls = []

        def transport(path, params):
            calls.append(path)
            if path == BAD:
                raise TimeoutError('pool-specific read timed out')
            return {'data': []}

        state = {'scan_metrics': {}}
        feed = self.feed(transport, state=state)
        with self.assertRaises(TimeoutError):
            feed(BAD)
        self.assertEqual(feed(GOOD), {'data': []})
        self.assertEqual(calls, [BAD, GOOD])
        self.assertEqual(state['scan_metrics']['isolated_timeouts'], 1)
        self.assertIsNone(state['provider_health']['gecko_trades'].get('retry_at'))
        self.assertIsNotNone(state['provider_health']['gecko_trade_pool:bad']['retry_at'])

    def test_local_cooldown_survives_runner_without_spending_call_budget(self):
        calls = []

        def transport(path, params):
            calls.append(path)
            if path == BAD and calls.count(BAD) == 1:
                raise TimeoutError('temporary pool timeout')
            return {'data': []}

        state = {'scan_metrics': {}}
        with self.assertRaises(TimeoutError):
            self.feed(transport, state=state)(BAD)
        # Simulate a new Actions runner before the five-minute cooldown expires.
        state = copy.deepcopy(state)
        later = self.feed(transport, state=state, when=NOW + dt.timedelta(minutes=4))
        with self.assertRaises(research_feed.Deferred):
            later(BAD)
        self.assertEqual(later.requests, 0)
        self.assertEqual(later(GOOD), {'data': []})
        # After local cooldown, the originally timed-out pool gets a chance.
        recovered = self.feed(transport, state=state, when=NOW + dt.timedelta(minutes=6))
        self.assertEqual(recovered(BAD), {'data': []})
        self.assertNotIn('gecko_trade_pool:bad', state['provider_health'])
        self.assertEqual(calls, [BAD, GOOD, BAD])

    def test_urllib_wrapped_timeout_is_also_local(self):
        def transport(path, params):
            if path == BAD:
                raise urllib.error.URLError(TimeoutError('read timed out'))
            return {'data': []}

        state = {'scan_metrics': {}}
        feed = self.feed(transport, state=state)
        with self.assertRaises(urllib.error.URLError):
            feed(BAD)
        self.assertEqual(feed(GOOD), {'data': []})
        self.assertEqual(state['scan_metrics']['isolated_timeouts'], 1)

    def test_http_429_remains_global_and_honours_retry_after(self):
        calls = []

        def transport(path, params):
            calls.append(path)
            if path == BAD:
                raise urllib.error.HTTPError(
                    'https://example.invalid', 429, 'Too Many Requests',
                    {'Retry-After': '900'}, io.BytesIO())
            return {'data': []}

        state = {'scan_metrics': {}}
        feed = self.feed(transport, state=state)
        with self.assertRaises(urllib.error.HTTPError):
            feed(BAD)
        with self.assertRaises(research_feed.Deferred):
            feed(GOOD)
        next_cycle = self.feed(transport, state=state, when=NOW + dt.timedelta(minutes=5))
        with self.assertRaises(research_feed.Deferred):
            next_cycle(GOOD)
        self.assertEqual(next_cycle.requests, 0)
        self.assertEqual(calls, [BAD])
        after_cooldown = self.feed(transport, state=state, when=NOW + dt.timedelta(minutes=16))
        self.assertEqual(after_cooldown(GOOD), {'data': []})
        self.assertNotIn('gecko_trade_pool:bad', state['provider_health'])
        self.assertEqual(state['provider_health']['gecko_trades']['consecutive_failures'], 0)

    def test_http_502_remains_global_not_pool_specific(self):
        def transport(path, params):
            if path == BAD:
                raise urllib.error.HTTPError('u', 502, 'Bad Gateway', {}, io.BytesIO())
            return {'data': []}

        state = {'scan_metrics': {}}
        feed = self.feed(transport, state=state)
        with self.assertRaises(urllib.error.HTTPError):
            feed(BAD)
        with self.assertRaises(research_feed.Deferred):
            feed(GOOD)
        self.assertIn('retry_at', state['provider_health']['gecko_trades'])

    def test_multi_quote_timeout_remains_global(self):
        def transport(path, params):
            if '/multi/' in path:
                raise TimeoutError('provider-wide quote timeout')
            return {'data': []}

        state = {'scan_metrics': {}}
        feed = self.feed(transport, state=state)
        with self.assertRaises(TimeoutError):
            feed('/networks/solana/pools/multi/bad,good')
        with self.assertRaises(research_feed.Deferred):
            feed('/networks/solana/trending_pools')
        self.assertIn('retry_at', state['provider_health']['gecko_quotes'])

    def test_bounded_request_budget_still_enforced(self):
        state = {'scan_metrics': {}}
        feed = self.feed(lambda *args: {'data': []}, state=state)
        for n in range(4):
            self.assertEqual(feed(f'/networks/solana/pools/{n}/trades'), {'data': []})
        with self.assertRaises(research_feed.Deferred):
            feed('/networks/solana/pools/fifth/trades')
        self.assertEqual(feed.requests, 4)
        self.assertEqual(state['scan_metrics']['requests'], 4)
        self.assertGreaterEqual(feed.clock(), 6.3)

    def test_pool_scope_only_applies_to_canonical_trade_endpoint(self):
        self.assertEqual(research_feed.trade_pool_scope(BAD), 'gecko_trade_pool:bad')
        for path in ['/trades', '/pool/trades', '/networks/eth/pools/bad/trades',
                     '/networks/solana/pools/multi/a,trades',
                     '/networks/solana/pools/bad/trades/extra']:
            self.assertIsNone(research_feed.trade_pool_scope(path))

    def test_local_circuit_storage_bounded(self):
        state = {'scan_metrics': {}}
        for n in range(70):
            feed = self.feed(
                lambda *args: (_ for _ in ()).throw(TimeoutError('timeout')),
                state=state, when=NOW + dt.timedelta(minutes=n))
            with self.assertRaises(TimeoutError):
                feed(f'/networks/solana/pools/pool{n}/trades')
        local_circuits = [key for key in state['provider_health'] if key.startswith('gecko_trade_pool:')]
        self.assertLessEqual(len(local_circuits), 64)


if __name__ == '__main__':
    unittest.main()
