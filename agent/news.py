"""Bounded public RSS context. Headlines are risk flags, never trading commands.

No symbol-name matching, inferred bullish sentiment or fabricated news coverage.
A successful feed with no recent relevant headline is explicitly distinct from
an unavailable feed. Entries stop when both sources are unavailable.
"""
import datetime as dt
import email.utils
import re
import urllib.request
import xml.etree.ElementTree as ET
from .adaptive import stamp

FEEDS = {'solana_status':'https://status.solana.com/history.rss',
         'coindesk':'https://www.coindesk.com/arc/outboundfeeds/rss/'}
MAX_BYTES = 256000


def download(url):
    req = urllib.request.Request(url,headers={'User-Agent':'PaperResearch/1.0','Accept':'application/rss+xml,application/xml'})
    with urllib.request.urlopen(req,timeout=4) as r:
        return r.read(MAX_BYTES+1)


def parse(data, source, current):
    if len(data)>MAX_BYTES: raise ValueError('RSS exceeds size budget')
    root = ET.fromstring(data)
    if root.tag != 'rss': raise ValueError('Not RSS')
    latest=None
    result=[]
    for item in root.findall('.//item')[:40]:
        title = re.sub('<[^>]*>','',item.findtext('title') or '').strip()[:180]
        link = item.findtext('link') or ''
        try: at=email.utils.parsedate_to_datetime(item.findtext('pubDate') or '')
        except (TypeError, ValueError): continue
        if at.tzinfo is None: continue
        if at<=current and (latest is None or at>latest): latest=at
        if not 0 <= (current-at).total_seconds() <= 21600: continue
        if not link.startswith('https://'): continue
        low=title.lower()
        relevant=source=='solana_status' or bool(re.search(r'\b(solana|crypto|cryptocurrency|bitcoin|market)\b',low))
        adverse=bool(re.search(r'\b(hack|hacked|exploit|exploited|outage|halted|breach|plunge|plunges|crash|crashes)\b',low))
        # Resolved incidents are context, not a fresh emergency.
        resolved=bool(re.search(r'\b(resolved|restored|resumes|postmortem)\b',low))
        if relevant:
            result.append(dict(title=title,url=link,published_at=at.isoformat(),source=source,
                               risk_flag=adverse and not resolved))
    if source=='coindesk' and (latest is None or (current-latest).total_seconds()>86400):
        raise ValueError('News feed has no article from the last 24 hours')
    return result


def refresh(state, current, fetch=download):
    r=state.setdefault('research',{}); previous=r.get('news_v1') or {}
    checked=stamp(previous.get('checked_at'))
    if checked and 0 <= (current-checked).total_seconds()<900: return previous
    sources={};items=[]
    for name,url in FEEDS.items():
        try:
            rows=parse(fetch(url),name,current);items.extend(rows)
            sources[name]={'status':'OK','recent_relevant_items':len(rows),'url':url}
        except Exception as exc:
            sources[name]={'status':'UNAVAILABLE','error':type(exc).__name__,'url':url}
    ok=sum(s['status']=='OK' for s in sources.values())
    risks=[x for x in items if x['risk_flag']]
    result=dict(checked_at=current.isoformat(),status='OK' if ok==2 else 'PARTIAL' if ok else 'UNAVAILABLE',
                sources=sources,items=items[:20],risk_off=bool(risks),risk_evidence=risks[:5],
                scope='Solana network incidents and broad crypto headlines; individual meme-token news unverified')
    r['news_v1']=result
    return result
