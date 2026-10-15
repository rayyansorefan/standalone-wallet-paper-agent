"""Conservative read-only Rugcheck screening: no safety result -> no entry."""
import json, re, urllib.parse, urllib.request

def screen_token(mint):
    if not re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{32,44}',mint or ''):
        return False
    url='https://api.rugcheck.xyz/v1/tokens/'+urllib.parse.quote(mint,safe='')+'/report/summary'
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'PaperAgentResearch/0.1'}),timeout=12) as r:
            result=json.load(r)
        score=result.get('score_normalised')
        risks=result.get('risks')
        if not isinstance(risks,list) or score is None or float(score)>25:return False
        for risk in risks:
            if not isinstance(risk,dict) or risk.get('level') in ('danger','critical','high'):return False
            title=str(risk.get('name','')).lower()
            if any(v in title for v in ('mint authority','freeze authority','cannot sell','honeypot')):return False
        return True
    except (ValueError, TypeError, OSError, KeyError):return False
