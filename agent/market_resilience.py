"""Quote-only, free public DEX Screener fallback for EXISTING paper positions.

No trade/sender discovery is attempted from market summaries. Only prices
obtained from the EXACT requested Solana pair are accepted. Never fabricate
quotes or treat the fallback as security approval for NEW positions.
"""
import json
import math
import re
import urllib.parse
import urllib.request

BASE = 'https://api.dexscreener.com/latest/dex/pairs/solana/'
SOL_ADDRESS = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
MAX_PAIRS = 30
MAX_BYTES = 600_000
TIMEOUT_SECONDS = 7


def fetch_pairs(addresses, *, transport=None):
    """Return {pool_address: base_token_price_usd} from a fresh bounded read.

    The caller supplies dependency-injected transport in deterministic tests.
    Failures raise (rather than applying cached, wrong-pair or invented prices).
    """
    unique=list(dict.fromkeys(addresses))
    if not unique:
        return {}
    if len(unique)>MAX_PAIRS or any(not isinstance(a,str) or not SOL_ADDRESS.fullmatch(a) for a in unique):
        raise ValueError('Invalid or excessive Solana pair addresses')
    if transport is None:
        def transport(url):
            req=urllib.request.Request(url,headers={
                'Accept':'application/json',
                'User-Agent':'ResearchPaperWalletAgent/1.0 (paper-only)'})
            with urllib.request.urlopen(req,timeout=TIMEOUT_SECONDS) as response:
                raw=response.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:
                raise ValueError('Quote response exceeds bounded size')
            return json.loads(raw)
    url=BASE+','.join(urllib.parse.quote(a,safe='') for a in unique)
    payload=transport(url)
    if not isinstance(payload,dict) or not isinstance(payload.get('pairs'),list):
        raise ValueError('DEX Screener pair response not usable')
    result={}
    requested=set(unique)
    for pair in payload['pairs']:
        if not isinstance(pair,dict) or pair.get('chainId')!='solana':
            continue
        address=pair.get('pairAddress')
        if address not in requested or address in result:
            continue
        base=pair.get('baseToken') or {}
        if not isinstance(base,dict) or not SOL_ADDRESS.fullmatch(str(base.get('address',''))):
            continue
        try: value=float(pair.get('priceUsd'))
        except (ValueError,TypeError,OverflowError):continue
        if math.isfinite(value) and value>0:
            result[address]=value
    return result
