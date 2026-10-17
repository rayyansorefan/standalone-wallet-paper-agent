import datetime as dt
import io
import unittest
import urllib.error
from unittest.mock import patch
from agent.primary_feed import PrimaryFeed, MIN_SPACING
from agent import core

class Clock:
    def __init__(self):self.t=0
    def __call__(self):return self.t
    def sleep(self,seconds):self.t+=seconds

class PrimaryFeedTests(unittest.TestCase):
    def make(self,health=None,opener=None):
        clock=Clock();now=dt.datetime(2026,10,16,19,tzinfo=dt.timezone.utc)
        health={} if health is None else health
        feed=PrimaryFeed(health,clock,clock.sleep,now=lambda:now+dt.timedelta(seconds=clock.t),opener=opener or (lambda *a,**k:io.BytesIO(b'{"data":[]}')))
        return feed,clock,health

    def test_primary_calls_are_spaced_without_extra_requests(self):
        f,c,h=self.make();f.read('a');f.read('b');f.read('c')
        self.assertAlmostEqual(c.t,2*MIN_SPACING);self.assertEqual(h['requests'],3)

    def test_429_honours_retry_after_and_persists_across_runner(self):
        def fail(*a,**k):raise urllib.error.HTTPError('https://example.com',429,'rate',{'Retry-After':'600'},None)
        f,c,h=self.make(opener=fail)
        with self.assertRaises(urllib.error.HTTPError):f.read('a')
        self.assertEqual(h['retry_at'],'2026-10-16T19:10:00+00:00')
        g,_,_=self.make(health=h,opener=lambda *a,**k:self.fail('must not call provider'))
        with self.assertRaisesRegex(RuntimeError,'cooling down'):g.read('b')
        self.assertEqual(g.requests,0)

    def test_retry_after_http_date_and_malformed_header(self):
        for header,expected in [('Fri, 16 Oct 2026 19:10:00 GMT','19:10:00'),('nonsense','19:05:00')]:
            def fail(*a,**k):raise urllib.error.HTTPError('x',429,'rate',{'Retry-After':header},None)
            f,_,h=self.make(opener=fail)
            with self.assertRaises(urllib.error.HTTPError):f.read('a')
            self.assertIn(expected,h['retry_at'])

    def test_consecutive_429s_escalate_across_independent_five_minute_runs(self):
        h={}
        calls=[]
        def fail(*a,**k):
            calls.append(1)
            raise urllib.error.HTTPError('https://example.com',429,'rate',{},None)
        base=dt.datetime(2026,10,16,19,tzinfo=dt.timezone.utc)
        for minutes,strikes,delay in [(0,1,300),(6,2,600),(17,3,1200)]:
            c=Clock()
            now=lambda minute=minutes,clock=c:base+dt.timedelta(minutes=minute,seconds=clock.t)
            f=PrimaryFeed(h,c,c.sleep,now=now,opener=fail)
            with self.assertRaises(urllib.error.HTTPError):
                f.read('/trades')
            self.assertEqual(h['rate_limit_strikes'],strikes)
            self.assertEqual((dt.datetime.fromisoformat(h['retry_at'])-now()).total_seconds(),delay)
        self.assertEqual(len(calls),3)
        c=Clock()
        f=PrimaryFeed(h,c,c.sleep,now=lambda:base+dt.timedelta(minutes=20),opener=fail)
        with self.assertRaisesRegex(RuntimeError,'cooling down'):
            f.read('/trades')
        self.assertEqual(f.requests,0)
        self.assertEqual(len(calls),3)

    def test_strikes_decay_after_one_hour_and_success_keeps_no_stale_cooldown(self):
        h={}
        def fail(*a,**k):
            raise urllib.error.HTTPError('https://example.com',429,'rate',{},None)
        base=dt.datetime(2026,10,16,19,tzinfo=dt.timezone.utc)
        c=Clock()
        PrimaryFeed(h,c,c.sleep,now=lambda:base,opener=fail)
        f=PrimaryFeed(h,c,c.sleep,now=lambda:base,opener=fail)
        with self.assertRaises(urllib.error.HTTPError):f.read('/trades')
        g=PrimaryFeed(h,Clock(),lambda _:None,now=lambda:base+dt.timedelta(hours=2),opener=fail)
        with self.assertRaises(urllib.error.HTTPError):g.read('/trades')
        self.assertEqual(h['rate_limit_strikes'],1)
        recovery=PrimaryFeed(h,Clock(),lambda _:None,now=lambda:base+dt.timedelta(hours=2,minutes=6),
                             opener=lambda *a,**k:io.BytesIO(b'{"data":[]}'))
        self.assertEqual(recovery.read('/trades'),{'data':[]})
        self.assertIsNone(h['retry_at'])
        self.assertEqual(h['http_status'],200)

    def test_deadline_never_issues_another_request(self):
        f,c,h=self.make();c.t=60
        with self.assertRaisesRegex(RuntimeError,'budget exhausted'):f.read('a')
        self.assertEqual(h['requests'],0)

    def test_core_never_immediately_retries_429(self):
        def fail(*a,**k):raise urllib.error.HTTPError('x',429,'rate',{},None)
        f,c,h=self.make(opener=fail)
        with patch.object(core,'_PRIMARY_FEED',f):
            with self.assertRaisesRegex(RuntimeError,'Primary rate limit'):core.api('/x')
        self.assertEqual(f.requests,1);self.assertEqual(c.t,0)

    def test_invalid_json_is_not_a_success_and_recovery_clears_cooldown(self):
        f,c,h=self.make(opener=lambda *a,**k:io.BytesIO(b'not-json'))
        with self.assertRaises(ValueError):f.read('x')
        self.assertNotIn('last_success_at',h)
        h['retry_at']='2026-10-16T18:00:00+00:00'
        g,_,_=self.make(health=h);g.read('x');self.assertIsNone(h['retry_at'])
