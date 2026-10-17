"""Paced primary market reads with persisted 429 backoff, never synthetic prices."""
import datetime as dt
import email.utils
import json
import time
import urllib.error
import urllib.request

UTC=dt.timezone.utc
MIN_SPACING=3.1
BUDGET_SECONDS=70
TIMEOUT_SECONDS=18


class PrimaryFeed:
    def __init__(self, health, clock=time.monotonic, sleep=time.sleep, now=None, opener=None):
        self.health=health;self.clock=clock;self.sleep=sleep
        self.now=now or (lambda:dt.datetime.now(UTC))
        self.opener=opener or urllib.request.urlopen
        self.started=clock();self.last=None;self.requests=0
        self.health.update(requests=0,spacing_seconds=MIN_SPACING,budget_seconds=BUDGET_SECONDS)

    def read(self, request):
        current=self.now()
        try:until=dt.datetime.fromisoformat(self.health.get('retry_at') or '')
        except (ValueError,TypeError):until=None
        if until and until.tzinfo and current<until:
            raise RuntimeError('Primary provider cooling down until '+until.isoformat())
        wait=max(0,MIN_SPACING-(self.clock()-self.last)) if self.last is not None else 0
        if self.clock()-self.started+wait+TIMEOUT_SECONDS>BUDGET_SECONDS:
            raise RuntimeError('Primary provider cycle time budget exhausted')
        if wait:self.sleep(wait)
        self.last=self.clock();self.requests+=1;self.health['requests']=self.requests
        try:
            with self.opener(request,timeout=TIMEOUT_SECONDS) as response:
                raw=response.read(3_000_001)
                if len(raw)>3_000_000:raise ValueError('Primary payload exceeds size budget')
                result=json.loads(raw)
            if not isinstance(result,dict) or 'errors' in result:
                raise ValueError('Malformed primary market response')
        except urllib.error.HTTPError as exc:
            if exc.code==429:
                # Repeated 429s five minutes apart mean a 60-second cooldown
                # is inadequate. Retain strikes across saved cycles, spacing
                # requests more conservatively WITHOUT extra retries or calls.
                previous=self.health.get('last_rate_limit_at')
                try:previous=dt.datetime.fromisoformat(previous) if previous else None
                except (ValueError,TypeError):previous=None
                within_hour=bool(previous and previous.tzinfo and
                                 dt.timedelta(0)<=current-previous<=dt.timedelta(hours=1))
                strikes=min(5,(int(self.health.get('rate_limit_strikes',0)) if within_hour else 0)+1)
                delay=min(3600,300*2**(strikes-1))
                value=exc.headers.get('Retry-After') if exc.headers else None
                try:retry=float(value)
                except (ValueError,TypeError):
                    try:retry=(email.utils.parsedate_to_datetime(value)-current).total_seconds()
                    except (ValueError,TypeError):retry=0
                if retry==retry:delay=max(delay,min(86400,retry))
                self.health.update(http_status=429,rate_limit_strikes=strikes,
                                   last_rate_limit_at=current.isoformat(),
                                   retry_at=(self.now()+dt.timedelta(seconds=delay)).isoformat(),
                                   last_error='HTTP 429; adaptive persisted provider cooldown; no immediate retry')
            raise
        self.health.update(http_status=200,retry_at=None,last_error=None,last_success_at=self.now().isoformat())
        return result
