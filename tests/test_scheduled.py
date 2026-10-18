import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import core, scheduled


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.current = dt.datetime(2026, 10, 15, 22, 10, 1, tzinfo=core.UTC)
        self.state = core.blank_state()
        self.state['last_run'] = (self.current - dt.timedelta(minutes=5)).isoformat()

    def test_two_trigger_sources_cannot_repeat_a_recent_cycle(self):
        self.state['last_run'] = (self.current - dt.timedelta(seconds=20)).isoformat()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'state.json'
            core.save(self.state, path)
            before = path.read_bytes()
            runner = mock.Mock()
            self.assertFalse(scheduled.execute(path, Path(root) / 'feed.json', self.current, runner))
            runner.assert_not_called()
            self.assertEqual(path.read_bytes(), before)

    def test_boundary_trigger_is_deduplicated(self):
        self.state['last_run'] = (self.current - dt.timedelta(seconds=2)).isoformat()
        self.assertFalse(scheduled.should_run(self.state, self.current))

    def test_next_five_minute_cycle_preserves_account_and_records_source(self):
        self.state['positions'] = [{'token': 'existing-paper-position'}]
        self.state['cash_gbp'] = 1989.9
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'state.json'
            feed = Path(root) / 'feed.json'
            core.save(self.state, path)
            def run(path):
                state = core.load(path)
                state['last_run'] = self.current.isoformat()
                state['completed_cycles'] += 1
                return state
            with mock.patch.dict('os.environ', {'GITHUB_EVENT_NAME': 'schedule', 'GITHUB_RUN_ID': '123'}):
                self.assertTrue(scheduled.execute(path, feed, self.current, run))
            saved = core.load(path)
            self.assertEqual(saved['positions'], self.state['positions'])
            self.assertEqual(saved['cash_gbp'], 1989.9)
            self.assertEqual(saved['starting_gbp'], 2000)
            self.assertEqual(saved['execution']['event'], 'schedule')
            self.assertEqual(saved['execution']['run_id'], '123')
            from agent.profitability import diagnostic
            published=json.loads(feed.read_text())
            self.assertEqual(published.pop('profitability_diagnostics'),diagnostic(saved['closed']))
            self.assertEqual(published, {k: v for k, v in saved.items() if k != 'seen_trades'})
            self.assertFalse(scheduled.should_run(saved, self.current + dt.timedelta(seconds=30)))

    def test_missing_account_cannot_be_restarted(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(FileNotFoundError):
                scheduled.execute(Path(root) / 'missing.json')

    def test_same_slot_and_bad_timestamp_fail_closed(self):
        self.state['execution'] = {'slot': int(self.current.timestamp()) // 300}
        self.assertFalse(scheduled.should_run(self.state, self.current))
        self.state['last_run'] = 'invalid'
        with self.assertRaises(ValueError):
            scheduled.should_run(self.state, self.current)
