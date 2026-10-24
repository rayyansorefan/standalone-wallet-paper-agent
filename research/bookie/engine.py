#!/usr/bin/env python3
"""Research-only sports snapshot collector. No wagering, logins or unlicensed scraping."""
import datetime as dt
import json
import math
import os
import statistics
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "docs" / "bookie" / "data.json"
SPORTS = [x.strip() for x in os.getenv("SPORT_KEYS", "basketball_nba,americanfootball_nfl,baseball_mlb").split(",") if x.strip()]
MAX_SPORTS = min(max(int(os.getenv("SPORTS_PER_RUN", "2")), 1), 15)
UTC = dt.timezone.utc
def now(): return dt.datetime.now(UTC)
def stamp(value=None): return (value or now()).isoformat(timespec="seconds").replace("+00:00","Z")
def parse(t):
    try: return dt.datetime.fromisoformat(t.replace("Z","+00:00"))
    except (TypeError, ValueError, AttributeError): return None
def bound(x,a,b): return max(a,min(b,x))
def read_data():
    if DEST.exists():
        try:
            data=json.loads(DEST.read_text())
            if data.get("schema")==2: return data
        except (OSError,ValueError): pass
    return {"schema":2,"generated_at":None,"last_success":None,"source_status":"NOT_CONFIGURED","source":"The Odds API v4 (licensed reference prices; no bet365 UK feed)","scanned_events":0,"source_sports":[],"quota_remaining":None,"candidates":[],"watchlist":[],"history":[],"model":{},"messages":[]}
def api_get(url,key):
    request=urllib.request.Request(url,headers={"User-Agent":"BookieResearchHub/1.0","Accept":"application/json"})
    with urllib.request.urlopen(request,timeout=22) as resp:
        value=json.load(resp); remaining=resp.headers.get("x-requests-remaining")
    return value, int(remaining) if remaining and remaining.isdigit() else None
def odds_url(sport,key):
    return ("https://api.the-odds-api.com/v4/sports/"+urllib.parse.quote(sport,safe="")+"/odds/?"+
            urllib.parse.urlencode({"apiKey":key,"regions":"uk","markets":"h2h","oddsFormat":"decimal","dateFormat":"iso"}))
def scores_url(sport,key):
    return ("https://api.the-odds-api.com/v4/sports/"+urllib.parse.quote(sport,safe="")+"/scores/?"+
            urllib.parse.urlencode({"apiKey":key,"daysFrom":3,"dateFormat":"iso"}))
def classify_prob(p): return "low" if p<.35 else ("high" if p>.65 else "middle")
def calibration(history,sport,bucket):
    rows=[h for h in history if h.get("settled") in (0,1) and h.get("sport")==sport and classify_prob(h.get("first_probability",.5))==bucket]
    # Calibration is learned only from predictions frozen before kickoff; prior shrinks tiny samples.
    n=len(rows)
    residual=sum(h["settled"]-h["first_probability"] for h in rows)
    bias=bound(residual/(n+80),-.04,.04) if n>=40 else 0
    brier=statistics.mean((h["first_probability"]-h["settled"])**2 for h in rows) if n else None
    return {"n":n,"bias":round(bias,5),"brier":round(brier,5) if brier is not None else None}
def settlement(scores):
    out={}
    for event in scores:
        if not event.get("completed"): continue
        values=event.get("scores") or []
        if len(values)<2: continue
        try: mapping={v["name"]:int(v["score"]) for v in values}
        except (KeyError,ValueError,TypeError): continue
        home,away=event.get("home_team"),event.get("away_team")
        if home not in mapping or away not in mapping: continue
        winner=home if mapping[home]>mapping[away] else away if mapping[away]>mapping[home] else "Draw"
        out[event.get("id")]=winner
    return out
def score_previous(history,results):
    for h in history:
        if h.get("settled") in (0,1): continue
        winner=results.get(h.get("event_id"))
        if winner is not None:
            h["settled"]=int(h["selection"]==winner);h["settled_at"]=stamp()
def summarize_model(history):
    settled=[h for h in history if h.get("settled") in (0,1)]
    brier=statistics.mean((h["first_probability"]-h["settled"])**2 for h in settled) if settled else None
    missed=[h for h in settled if h.get("first_decision")=="WATCH" and h.get("first_book_odds")]
    missing_wins=sum(h["settled"] for h in missed)
    # Hindsight record, not an instruction to bet; includes losing missed selections.
    shadow_profit=sum((h["first_book_odds"]-1 if h["settled"] else -1) for h in missed)
    buckets={}
    for sport in sorted({h.get("sport") for h in history if h.get("sport")}):
        buckets[sport]={b:calibration(settled,sport,b) for b in ("low","middle","high")}
    return {"settled_forecasts":len(settled),"brier":round(brier,4) if brier is not None else None,
            "missed_watch_decisions":len(missed),"missed_watch_wins":missing_wins,
            "missed_watch_shadow_units":round(shadow_profit,2),
            "adjustments_by_sport":buckets,
            "method":"Sport × probability-bin shrinkage (80 prior observations; update only after >=40 settled predictions). Pre-kickoff probabilities remain immutable. Watch outcomes scored whether they won or lost."}
def event_rows(event,historical):
    event_id=event.get("id");sport=event.get("sport_key","unknown")
    start=parse(event.get("commence_time"))
    if not event_id or not start or start<=now() or start>now()+dt.timedelta(hours=48): return []
    sources=[]
    for book in event.get("bookmakers",[]):
        for market in book.get("markets",[]):
            if market.get("key")!="h2h": continue
            outcomes=market.get("outcomes") or []
            try: prices={v["name"]:float(v["price"]) for v in outcomes if float(v["price"])>1}
            except (KeyError,ValueError,TypeError): continue
            if len(prices)<2: continue
            margin=sum(1/x for x in prices.values())
            if not (.95<margin<1.35): continue
            sources.append({"key":book.get("key",""),"title":book.get("title",""),"timestamp":book.get("last_update"),"prices":prices,
                            "fair":{s:(1/o)/margin for s,o in prices.items()},"margin":margin})
    external=[x for x in sources if x["key"] not in ("bet365","bet365_uk")]
    if len(external)<3: return []
    result=[]
    for selection in sorted(set().union(*(x["fair"].keys() for x in external))):
        prices=[x["fair"][selection] for x in external if selection in x["fair"]]
        if len(prices)<3:continue
        centre=statistics.median(prices)
        disagreement=statistics.median(abs(v-centre) for v in prices)*1.4826
        bucket=classify_prob(centre)
        cal=calibration(historical,sport,bucket)
        adj=bound(centre+cal["bias"],.001,.999)
        uncertainty=max(.045,2*disagreement+.015)
        low=bound(adj-uncertainty,.001,.999)
        quote=next((x for x in sources if x["key"] in ("bet365","bet365_uk") and selection in x["prices"]),None)
        offered=quote["prices"][selection] if quote else None
        age=(now()-parse(quote["timestamp"])).total_seconds()/60 if quote and parse(quote["timestamp"]) else None
        threshold=math.ceil((1/low)*100)/100
        val=round(low*offered-1,4) if offered else None
        allowed=(offered is not None and age is not None and age<=30 and low>.52 and offered>=threshold and val>.02)
        ident="|".join([sport,event_id,"h2h",selection])
        old=next((h for h in historical if h.get("id")==ident),None)
        if old is None:
            old={"id":ident,"event_id":event_id,"sport":sport,"event":event.get("home_team","")+" vs "+event.get("away_team",""),
                 "start":event.get("commence_time"),"selection":selection,"first_seen":stamp(),
                 "first_probability":round(centre,5),"first_book_odds":offered,
                 "first_decision":"BET_CANDIDATE" if allowed else "WATCH","settled":None}
            historical.append(old)
        result.append({"id":ident,"sport":sport,"event":old["event"],"start":event["commence_time"],
                       "selection":selection,"market":"Match winner (moneyline)","book_odds":offered,"book_timestamp":quote["timestamp"] if quote else None,
                       "source_count":len(prices),"reference_probability":round(centre,4),
                       "calibrated_probability":round(adj,4),"lower_probability":round(low,4),
                       "uncertainty":round(uncertainty,4),"min_odds":threshold,
                       "conservative_ev":val,"status":"BET_CANDIDATE" if allowed else "WATCH",
                       "reason":"Verified, fresh bet365 quote + positive conservative EV" if allowed else ("NO BET365 PRICE" if not quote else "Insufficient conservative edge or quote freshness")})
    return result
def main():
    data=read_data(); historic=data["history"]; key=os.getenv("ODDS_API_KEY","").strip()
    data["generated_at"]=stamp();data["messages"]=[];data["candidates"]=[]
    if not key:
        data.update({"source_status":"NOT_CONFIGURED","watchlist":[],"scanned_events":0,"source_sports":[]})
        data["messages"]=["No licensed odds key configured. No real-time market data or bet365 prices verified. No new betting recommendations."]
    else:
        cycle=int(now().timestamp()//(4*3600))
        chosen=[SPORTS[(cycle+i)%len(SPORTS)] for i in range(min(MAX_SPORTS,len(SPORTS)))] if SPORTS else []
        seen=[];rows=[];remaining=None;fail=[]
        for sport in chosen:
            try:
                events,remaining=api_get(odds_url(sport,key),key)
                seen.append(sport)
                for event in events: rows.extend(event_rows(event,historic))
                # Scores checked once daily to conserve free-tier monthly quota.
                if now().hour<4 and remaining is not None and remaining>5:
                    scores,remaining=api_get(scores_url(sport,key),key)
                    score_previous(historic,settlement(scores))
            except Exception as exc:
                fail.append(sport+": "+type(exc).__name__+": "+str(exc)[:100])
        data["source_sports"]=seen;data["scanned_events"]=len({r["event"] for r in rows});data["quota_remaining"]=remaining
        data["watchlist"]=sorted([r for r in rows if r["status"]=="WATCH"],key=lambda x:(-x["lower_probability"],x["start"]))[:30]
        data["candidates"]=sorted([r for r in rows if r["status"]=="BET_CANDIDATE"],key=lambda x:-x["conservative_ev"])[:3]
        data["source_status"]="OK" if seen and not fail else ("PARTIAL" if seen else "ERROR")
        if seen: data["last_success"]=stamp()
        data["messages"]=fail or ["Cross-book UK odds are reference data; The Odds API does not list bet365. Watch signals are not bet365 approvals."]
        if not data["candidates"]:data["messages"].append("NO APPROVED BET — no verified bet365 positive-value offer.")
    # Never retain unlimited rows on public Pages. Keep unsettled plus latest settled forecasts.
    live=[h for h in historic if h.get("settled") is None]
    done=sorted([h for h in historic if h.get("settled") is not None],key=lambda h:h.get("settled_at",""),reverse=True)
    data["history"]=(live[-1500:]+done[:2500])
    data["model"]=summarize_model(data["history"])
    DEST.parent.mkdir(parents=True,exist_ok=True)
    DEST.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print(json.dumps({"status":data["source_status"],"sports":data["source_sports"],"candidates":len(data["candidates"]),
                      "watched":len(data["watchlist"]),"settled":data["model"]["settled_forecasts"],"bytes":DEST.stat().st_size}))
if __name__=="__main__":main()
