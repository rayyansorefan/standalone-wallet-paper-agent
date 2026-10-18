"""Broaden FREE Solana candidate discovery without inventing wallet transactions.

Independent DEX Screener profile/boost lists are paid promotional *discovery*
only, not security endorsements. A pair must have independently reported
price, pool address, mint, age, liquidity and 24h volume before consideration.
Any subsequent funded paper entry STILL needs real fresh wallet swaps from
GeckoTerminal, Rugcheck PASS, momentum/news and existing risk rules.
"""
import datetime as dt
import json
import math
import re
import urllib.parse
import urllib.request

SOL=re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
ROOT='https://api.dexscreener.com'
SOURCES=('/token-profiles/latest/v1','/token-boosts/top/v1')
MAX_MINTS=100
MAX_POOL_RESULTS=100
SEARCH_QUERIES=('SOL','USDC','BONK','AI')
CHUNK=30
TIMEOUT=7
MAX_BYTES=1_200_000
UTC=dt.timezone.utc


def numeric(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError,OverflowError):
        return None


def http_get(path):
    req=urllib.request.Request(ROOT+path,headers={
        'User-Agent':'PaperResearchWideDiscovery/1.0 (paper only)',
        'Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=TIMEOUT) as response:
        raw=response.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Free discovery response too large')
    return json.loads(raw)


def choose_pair(pair,now):
    if not isinstance(pair,dict) or pair.get('chainId')!='solana':
        return None
    address=pair.get('pairAddress');base=pair.get('baseToken') or {}
    mint=base.get('address') if isinstance(base,dict) else None
    if not isinstance(address,str) or not SOL.fullmatch(address) or not isinstance(mint,str) or not SOL.fullmatch(mint):
        return None
    price=numeric(pair.get('priceUsd'))
    liq=pair.get('liquidity') or {}
    volume=pair.get('volume') or {}
    changes=pair.get('priceChange') or {}
    txns=pair.get('txns') or {}
    h1=txns.get('h1') or {}
    created=numeric(pair.get('pairCreatedAt'))
    if created is None or created<1_500_000_000_000 or created>now.timestamp()*1000:
        return None
    age=(now.timestamp()*1000-created)/3_600_000
    liquidity=numeric(liq.get('usd'))
    v24=numeric(volume.get('h24'))
    if not price or price<=0 or liquidity is None or liquidity<100_000 or v24 is None or v24<150_000 or age<24:
        return None
    name=str((base.get('symbol') or 'TOKEN'))[:30]+'/DEX'
    return {'id':'solana_'+address,'pool':address,'mint':mint,'name':name,
            'liquidity_usd':liquidity,'volume_24h_usd':v24,
            'price_usd':price,'age_hours':age,
            'change_24h_pct':numeric(changes.get('h24')),
            'change_5m_pct':numeric(changes.get('m5')),
            'change_1h_pct':numeric(changes.get('h1')),
            'volume_1h_usd':numeric(volume.get('h1')),
            'buys_1h':numeric(h1.get('buys')),
            'sells_1h':numeric(h1.get('sells')),
            'fdv_usd':numeric(pair.get('fdv')),
            'market_cap_usd':numeric(pair.get('marketCap')),
            'discovery_source':'dexscreener_public_promoted_list',
            'promotion_is_not_safety_approval':True}


def discover(get=http_get,now=None):
    """Broad free search + 100 independently validated mints; no credentials.

    Provider failures only degrade optional breadth, not core scanner. A
    malformed source cannot authorise paper trades.
    """
    now=now or dt.datetime.now(UTC)
    addresses=[]
    issues=[]
    source_counts={}
    for source in SOURCES:
        try:
            data=get(source)
            if not isinstance(data,list):raise ValueError('profile list malformed')
            count=0
            for item in data:
                if not isinstance(item,dict) or item.get('chainId')!='solana':
                    continue
                mint=item.get('tokenAddress')
                if isinstance(mint,str) and SOL.fullmatch(mint) and mint not in addresses:
                    addresses.append(mint);count+=1
                if len(addresses)>=MAX_MINTS:break
            source_counts[source]=count
        except Exception:
            issues.append(source.split('/')[-2]+' unavailable')
        if len(addresses)>=MAX_MINTS:break
    # Public DEX search returns complete pair snapshots, unlike promotional
    # token lists. This expands the cheap opportunity universe without
    # pretending each pool has had a Rugcheck or on-chain swap read.
    # Each response is independently validated; search hits cannot
    # authorise wallet events or bypass later risk/age gates.
    pairs={}
    search_requests=0
    search_rows=0
    for query in SEARCH_QUERIES:
        try:
            search_requests+=1
            response=get('/latest/dex/search?q='+urllib.parse.quote(query,safe=''))
            if not isinstance(response,dict) or not isinstance(response.get('pairs'),list):
                raise ValueError('search response malformed')
            for raw in response['pairs'][:100]:
                search_rows+=1
                item=choose_pair(raw,now)
                if not item:continue
                item['discovery_source']='dexscreener_public_search'
                pairs.setdefault(item['pool'],item)
                if item['mint'] not in addresses and len(addresses)<MAX_MINTS:
                    addresses.append(item['mint'])
        except Exception:
            issues.append('public search unavailable')
    calls=0
    for i in range(0,len(addresses),CHUNK):
        batch=addresses[i:i+CHUNK]
        try:
            calls+=1
            response=get('/tokens/v1/solana/'+','.join(batch))
            if not isinstance(response,list):raise ValueError('pair batch malformed')
            for raw in response:
                item=choose_pair(raw,now)
                if item and item['mint'] in batch:
                    old=pairs.get(item['pool'])
                    if old is None or item['liquidity_usd']>old['liquidity_usd']:
                        pairs[item['pool']]=item
        except Exception:
            issues.append('pair batch unavailable')
    return list(pairs.values())[:MAX_POOL_RESULTS],{
        'sources':source_counts,'raw_token_mints':len(addresses),
        'qualified_pairs':len(pairs),'returned_pairs':min(len(pairs),MAX_POOL_RESULTS),
        'search_requests':search_requests,'search_rows_examined':search_rows,
        'batch_requests':calls,'coverage_target':MAX_POOL_RESULTS,
        'coverage_shortfall':max(0,MAX_POOL_RESULTS-min(len(pairs),MAX_POOL_RESULTS)),
        'errors':issues[:6]}
