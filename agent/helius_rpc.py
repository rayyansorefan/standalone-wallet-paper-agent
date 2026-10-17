"""Optional, FREE-tier Helius standard-RPC connectivity probe.

No key is stored in code, history, logs or diagnostics. Do not treat signatures
as decoded swaps or verified wallet activity. In particular, no paper entry
can be created by this probe. Uses one standard archival request at most
every 30 minutes, never paid enhanced parsing methods.
"""
import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request

URL = 'https://mainnet.helius-rpc.com/'
ADDRESS = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
INTERVAL = dt.timedelta(minutes=30)
MAX_BYTES = 120_000
TIMEOUT = 6
UTC = dt.timezone.utc


def timestamp(v):
    if not v:
        return None
    try:
        at = dt.datetime.fromisoformat(str(v).replace('Z','+00:00'))
        return at.astimezone(UTC) if at.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def standard_rpc(key, address, transport=None):
    """Read-only signatures for exactly one Solana account; never decode a swap."""
    if not isinstance(key,str) or not key.strip():
        raise ValueError('Helius secret is missing')
    if not isinstance(address,str) or not ADDRESS.fullmatch(address):
        raise ValueError('Invalid Solana account address')
    body={'jsonrpc':'2.0','id':1,'method':'getSignaturesForAddress',
          'params':[address,{'limit':5,'commitment':'confirmed'}]}
    if transport is None:
        def transport(url, data):
            req=urllib.request.Request(url,data=data,
                headers={'Content-Type':'application/json','Accept':'application/json'},
                method='POST')
            with urllib.request.urlopen(req,timeout=TIMEOUT) as resp:
                raw=resp.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:
                raise ValueError('RPC reply too large')
            return json.loads(raw)
    # The API key only enters the Helius HTTPS request. Never return/log URL.
    endpoint=URL+'?'+urllib.parse.urlencode({'api-key':key})
    reply=transport(endpoint,json.dumps(body).encode('utf-8'))
    if not isinstance(reply,dict) or reply.get('error') is not None or not isinstance(reply.get('result'),list):
        raise ValueError('Helius standard RPC returned unusable result')
    observed=reply['result']
    if len(observed)>5 or any(not isinstance(x,dict) or not isinstance(x.get('signature'),str) for x in observed):
        raise ValueError('Helius RPC signatures response malformed')
    return len(observed)


def probe(state, candidate_pools, now=None, *, key=None, rpc=standard_rpc):
    """Keep a bounded readiness status; never affect ledger, entries or provider status."""
    research=state.setdefault('research',{})
    health=research.setdefault('helius_rpc_v1',{})
    now=now or dt.datetime.now(UTC)
    # GitHub Actions supplies the key as an encrypted repository secret.
    # Do NOT persist any part of the key or unauthorised error URLs.
    if key is None:
        key=os.environ.get('HELIUS_API_KEY','')
    if not key:
        health.update(status='NOT_CONFIGURED',purpose='READ_ONLY_RPC_PROBE',
                      swap_decoding=False)
        return health
    last=timestamp(health.get('attempted_at'))
    if last and dt.timedelta(0)<=now-last<INTERVAL:
        return health
    pool=next((p.get('pool') for p in candidate_pools
               if isinstance(p,dict) and ADDRESS.fullmatch(str(p.get('pool','')))),None)
    if not pool:
        health.update(status='NO_ACCOUNT_TO_PROBE',purpose='READ_ONLY_RPC_PROBE',
                      swap_decoding=False)
        return health
    health.update(status='CHECKING',attempted_at=now.isoformat(),purpose='READ_ONLY_RPC_PROBE',
                  swap_decoding=False)
    try:
        n=rpc(key,pool)
        health.update(status='AVAILABLE',sampled_signatures=n,
                      last_success_at=now.isoformat())
    except Exception as exc:
        # Never expose exception strings; urllib failures may include the API key URL.
        health.update(status='UNAVAILABLE',sampled_signatures=None,
                      error_type=type(exc).__name__)
    return health
