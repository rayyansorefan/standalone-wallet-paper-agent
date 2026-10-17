"""Regression for expired primary market-data 429 cooldowns.

Intermittent provider outages must not become sticky false rate-limit reports.
No live orders, account mutation, API quota increase, or forced trades.
"""
import datetime as dt
import unittest
from unittest.mock import patch

from agent import core


class StubFeed:
    def __init__(self, retry_at):
        self.health={'retry_at':retry_at}
        self.calls=0

    def read(self, request):
        self.calls+=1
        if self.calls==1:
            raise ValueError('Transient malformed primary JSON response')
        return {'data':[]}


class CooldownRecovery(unittest.TestCase):
    def test_expired_cooldown_retries_transient_error_and_recovers(self):
        old=(dt.datetime.now(core.UTC)-dt.timedelta(minutes=1)).isoformat()
        feed=StubFeed(old)
        with patch.object(core,'_PRIMARY_FEED',feed),patch.object(core.time,'sleep'):
            result=core.api('/networks/solana/trending_pools')
        self.assertEqual(result,{'data':[]})
        self.assertEqual(feed.calls,2)

    def test_future_cooldown_remains_fail_closed_without_retries(self):
        future=(dt.datetime.now(core.UTC)+dt.timedelta(minutes=2)).isoformat()
        feed=StubFeed(future)
        with patch.object(core,'_PRIMARY_FEED',feed),patch.object(core.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'Primary rate limit'):
                core.api('/networks/solana/trending_pools')
        self.assertEqual(feed.calls,1)

    def test_missing_retry_at_allows_normal_transient_recovery(self):
        feed=StubFeed(None)
        with patch.object(core,'_PRIMARY_FEED',feed),patch.object(core.time,'sleep'):
            self.assertEqual(core.api('/networks/solana/trending_pools'),{'data':[]})
        self.assertEqual(feed.calls,2)


if __name__=='__main__':unittest.main()
