"""Bounded, persisted public-data access for V3 only. Never places orders.

Primary paper/V2 requests have priority and are deliberately unchanged.
Cooldowns survive ephemeral Actions runners; no retry loop consumes a cycle.
"""
import datetime as dt
import email.utils
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

UTC = dt.timezone.utc
MAX_REQUESTS = 4
TIME_BUDGET = 25
REQUEST_TIMEOUT = 8
MIN_SPACING = 2.1


class Deferred(RuntimeError):
    pass


def trade_pool_scope(path):
    """Only a well-formed pool trade URL gets a pool-local timeout circuit."""
    parts = path.strip('/').split('/')
    if (len(parts) == 5 and parts[:3] == ['networks', 'solana', 'pools']
            and parts[3] and parts[4] == 'trades'):
        return 'gecko_trade_pool:' + parts[3]
    return None


def is_timeout(exc):
    """Unwrap urllib timeout errors; never downgrade an HTTP 429 to local."""
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if isinstance(exc, TimeoutError):
        return True
    return isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError)


def stamp(value):
    try:
        t = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return t.astimezone(UTC) if t.tzinfo else None
    except (ValueError, TypeError):
        return None


def public_json(url, timeout=5):
    req = urllib.request.Request(url, headers={'Accept': 'application/json',
        'User-Agent': 'ResearchPaperWalletAgent/1.0 (paper-only)'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        # Bound untrusted provider payloads as well as latency.
        raw = response.read(3_000_001)
        if len(raw) > 3_000_000:
            raise ValueError('Research payload too large')
        return json.loads(raw)


def primary_window_delay(started, current):
    # Leave the primary engine's first provider window before supplemental work.
    # At most 60s, once per GitHub cycle; never sleep inside retry/backoff loops.
    return min(60.,max(0.,65.-(current-started).total_seconds()))


class ResearchFeed:
    def __init__(self, research, now, transport=None, clock=time.monotonic, sleep=time.sleep, defer_gecko=False):
        from .whales import fast_fetch
        self.r, self.now = research, now
        self.production = transport is None
        self.transport = transport or (lambda path,params:fast_fetch(path,params,timeout=REQUEST_TIMEOUT))
        self.clock, self.sleep = clock, sleep
        # The free DEX quote-only path does not contact GeckoTerminal, so
        # withholding a full 60 seconds protects no shared-provider quota.
        quiet = (primary_window_delay(now,dt.datetime.now(UTC))
                 if transport is None and os.getenv('GITHUB_ACTIONS')=='true' and not defer_gecko else 0)
        if quiet:
            sleep(quiet)
        if self.production:
            self.now = dt.datetime.now(UTC)
        self.started = clock()
        self.last_request = None
        self.requests = 0
        self.health = research.setdefault('provider_health', {})
        self.cache = research.setdefault('discovery_cache', {})
        self.metrics = research['scan_metrics']
        self.metrics.update(requests=0, cache_hits=0, deferred=0, isolated_timeouts=0,
                            quote_provider='geckoterminal',
                            primary_window_wait_seconds=round(quiet,3))

    def _reserve(self, group, scope=None):
        health = self.health.setdefault(group, {})
        current=dt.datetime.now(UTC) if self.production else self.now
        # Provider-wide HTTP 429/5xx is checked first. A different pool's read
        # timeout must not silence every supplemental swap feed for five minutes.
        for key in (group, scope):
            if not key:
                continue
            circuit = self.health.get(key, {})
            until = stamp(circuit.get('retry_at'))
            if until and current < until:
                self.metrics['deferred'] += 1
                raise Deferred(key + ' cooling down until ' + circuit['retry_at'])
        wait = max(0, MIN_SPACING - (self.clock()-self.last_request)) if self.last_request is not None else 0
        if self.requests >= MAX_REQUESTS or self.clock()-self.started+wait+REQUEST_TIMEOUT > TIME_BUDGET:
            self.metrics['deferred'] += 1
            raise Deferred('V3 request/time budget reserved for next cycle')
        if wait:
            self.sleep(wait)
        self.requests += 1
        self.metrics['requests'] = self.requests
        self.last_request = self.clock()
        return health

    def _failure(self, health, exc):
        count = min(health.get('consecutive_failures', 0)+1, 8)
        delay = min(3600, 300 * 2**(count-1))
        retry = None
        if isinstance(exc, urllib.error.HTTPError):
            header = exc.headers.get('Retry-After') if exc.headers else None
            try:
                retry = float(header)
            except (TypeError, ValueError):
                try:
                    retry = (email.utils.parsedate_to_datetime(header)-self.now).total_seconds()
                except (TypeError, ValueError):
                    pass
        # Honour longer provider cooldowns, capped at one day for malformed headers.
        delay = max(delay, min(86400, retry or 0))
        health.update(consecutive_failures=count, last_error=str(exc)[:180],
            http_status=getattr(exc, 'code', None),
            retry_at=((dt.datetime.now(UTC) if self.production else self.now)+dt.timedelta(seconds=delay)).isoformat(timespec='seconds'))

    def _call(self, group, operation, scope=None):
        health = self._reserve(group, scope)
        try:
            result = operation()
        except Exception as exc:
            if scope and is_timeout(exc):
                # Persist a pool-local circuit across Actions runners; a shared
                # 429/5xx or unknown failure still retains provider-wide backoff.
                self._failure(self.health.setdefault(scope, {}), exc)
                self.metrics['isolated_timeouts'] += 1
                pool_circuits = [k for k in self.health if k.startswith('gecko_trade_pool:')]
                for key in pool_circuits[:-64]:
                    self.health.pop(key, None)
            else:
                self._failure(health, exc)
            raise
        health.update(consecutive_failures=0, last_error=None, http_status=200,
                      retry_at=None, last_success=self.now.isoformat(timespec='seconds'))
        if scope:
            # A successful quote from this pool retires its expired circuit.
            self.health.pop(scope, None)
        return result

    def __call__(self, path, params=None):
        group = 'gecko_trades' if path.endswith('/trades') else 'gecko_quotes'
        scope = trade_pool_scope(path) if group == 'gecko_trades' else None
        key = path+'?'+urllib.parse.urlencode(params or {})
        is_discovery = 'trending_pools' in path
        cached = self.cache.get(key, {})
        at = stamp(cached.get('at'))
        if is_discovery and at and 0 <= (self.now-at).total_seconds() < 900:
            self.metrics['cache_hits'] += 1
            return cached['payload']
        def retrieve():
            result = self.transport(path, params)
            if not isinstance(result, dict) or 'errors' in result or 'data' not in result:
                raise ValueError('Malformed research feed')
            if is_discovery or path.endswith('/trades') or '/multi/' in path:
                if not isinstance(result['data'], list):
                    raise ValueError('Research list response missing')
            return result
        payload = self._call(group, retrieve, scope=scope)
        if is_discovery:
            self.cache[key] = {'at': self.now.isoformat(timespec='seconds'), 'payload': payload}
            self.r['discovery_cache'] = dict(list(self.cache.items())[-4:])
        return payload

    def fallback_quotes(self, addresses):
        """DEX Screener has quotes/counts, NOT identifiable wallet transactions."""
        requested = set(addresses)
        url = 'https://api.dexscreener.com/latest/dex/pairs/solana/' + ','.join(
            urllib.parse.quote(x, safe='') for x in addresses)
        payload = self._call('dexscreener_quotes', lambda: public_json(url))
        if not isinstance(payload, dict) or not isinstance(payload.get('pairs'), list):
            raise ValueError('Malformed DEX Screener pair response')
        result = []
        for pair in payload['pairs']:
            if pair.get('chainId') != 'solana' or pair.get('pairAddress') not in requested:
                continue
            created = pair.get('pairCreatedAt')
            # Translate documented fields only. Never infer swap senders from counts.
            result.append({'id':'solana_'+pair['pairAddress'],
                'relationships':{'base_token':{'data':{'id':'solana_'+str((pair.get('baseToken') or {}).get('address',''))}}},
                'attributes':{'address':pair['pairAddress'],
                    'name':str((pair.get('baseToken') or {}).get('symbol','?'))+'/'+str((pair.get('quoteToken') or {}).get('symbol','?')),
                    'base_token_price_usd':pair.get('priceUsd'),
                    'reserve_in_usd':(pair.get('liquidity') or {}).get('usd'),
                    'volume_usd':{'h24':(pair.get('volume') or {}).get('h24')},
                    'price_change_percentage':{'h24':(pair.get('priceChange') or {}).get('h24')},
                    'pool_created_at':dt.datetime.fromtimestamp(created/1000, UTC).isoformat() if isinstance(created,(int,float)) and created>0 else None}})
        self.metrics['quote_provider'] = 'dexscreener'
        return {'data': result}
