"""Optional licensed bet365 + comparator adapter (OddsPapi v4).
One odds board per four-hour run on the free tier; daily fixture list and
one result-grade check where quota permits. No account login or betting.
"""
import datetime as dt
import json
import os
import urllib.parse
import urllib.request

MAX_MONTHLY_CALLS=235  # 250 advertised monthly calls; reserve 15 for retries and validation.
COMPARATORS=os.getenv("ODDSPAPI_BOOKMAKERS","").strip()  # Empty = all; avoids unknown slugs.
FOCUS={11:0,12:1,15:2,10:3,13:4,14:5,16:6,19:7,17:8}
def call(data,key,path,params):
    month=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    usage=data.setdefault("papi_usage",{"month":month,"count":0})
    if usage["month"]!=month:usage.update(month=month,count=0)
    if usage["count"]>=MAX_MONTHLY_CALLS:
        raise RuntimeError("Monthly research quota budget exhausted: no extra data calls")
    usage["count"]+=1 # Count failures as potentially billed requests.
    query=urllib.parse.urlencode({**params,"apiKey":key})
    req=urllib.request.Request("https://api.oddspapi.io/v4/"+path+"?"+query,
                               headers={"Accept":"application/json","User-Agent":"BookieResearch/1.0"})
    with urllib.request.urlopen(req,timeout=25) as response:
        value=json.load(response)
    if isinstance(value,dict) and value.get("error"):
        raise RuntimeError("Provider returned an API error")
    return value
def eligible_market(m, sport_id):
    """Only unambiguous FULL MATCH 1X2 or 2-way winner markets, never props/spreads."""
    try:
        if int(m.get("sportId",-1)) != int(sport_id): return False
        if int(m.get("marketLength",0)) != len(m.get("outcomes") or []): return False
        count=int(m["marketLength"])
    except (TypeError,ValueError,KeyError):return False
    if m.get("playerProp") or m.get("handicap") not in (None,0,0.0): return False
    name=str(m.get("marketName","")).strip().lower()
    period=str(m.get("period") or "").lower()
    if period and period not in ("fulltime","match","full_time","overall","game"):return False
    kind=str(m.get("marketType","")).lower()
    if int(sport_id)==10:
        return count==3 and (name in ("full time result","match result","1x2","fulltime result")
                             or (kind=="1x2" and period in ("","fulltime","match")))
    return count==2 and (name in ("winner","match winner","game winner","moneyline","money line",
                                  "match winner including overtime","winner including overtime",
                                  "to win","match betting","match result (including overtime)")
                         or (kind in ("moneyline","winner","h2h") and period in ("","fulltime","match","game")))
def market_name_map(fixture, definitions):
    """Choose an explicitly documented match market from OddsPapi GET /markets."""
    sport=fixture.get("sportId")
    if not sport or not isinstance(definitions,list):return None
    active=(fixture.get("bookmakerOdds") or {}).get("bet365") or {}
    offered=active.get("markets") or {}
    choices=[m for m in definitions if eligible_market(m,sport) and str(m.get("marketId")) in offered]
    if not choices:return None
    choices.sort(key=lambda m:(str(m.get("marketName","")).lower() not in ("full time result","moneyline","money line","match winner"),int(m["marketId"])))
    market=choices[0]
    raw=market["outcomes"]
    if int(sport)==10:
        if [str(x.get("outcomeName","")).upper() for x in raw]!=["1","X","2"]:return None
        names=[fixture.get("participant1Name"),"Draw",fixture.get("participant2Name")]
    else:
        labels=[str(x.get("outcomeName","")).strip().lower() for x in raw]
        if labels not in (["1","2"],["home","away"],["player 1","player 2"],["team 1","team 2"],
                          [str(fixture.get("participant1Name","")).lower(),str(fixture.get("participant2Name","")).lower()]):
            return None
        names=[fixture.get("participant1Name"),fixture.get("participant2Name")]
    if not names[0] or not names[-1] or len(set(names))!=len(names):return None
    return str(market["marketId"]), {str(o["outcomeId"]):name for o,name in zip(raw,names)}
def normalize(board, definitions):
    mapping=market_name_map(board,definitions)
    if not mapping:return None
    mid,name_for_id=mapping
    books=[]
    for slug,b in (board.get("bookmakerOdds") or {}).items():
        if b.get("bookmakerIsActive") is False or b.get("suspended"):continue
        market=(b.get("markets") or {}).get(mid)
        if not market or market.get("marketActive") is False:continue
        offered=[];changed=[]
        for oid,name in name_for_id.items():
            outcome=(market.get("outcomes") or {}).get(oid)
            if not outcome:break
            price_obj=(outcome.get("players") or {}).get("0")
            if not price_obj or price_obj.get("active") is False:break
            try:price=float(price_obj.get("price",0))
            except (TypeError,ValueError):break
            if not (1.001<price<1000):break
            offered.append({"name":name,"price":price})
            if price_obj.get("changedAt"):changed.append(price_obj["changedAt"])
        if len(offered)!=len(name_for_id):continue
        books.append({"key":slug,"title":slug,"last_update":min(changed) if changed else None,
                      "markets":[{"key":"h2h","outcomes":offered}]})
    if not any(x["key"]=="bet365" for x in books):return None
    return {"id":board.get("fixtureId"),"sport_key":(board.get("sportName") or str(board.get("sportId"))).lower().replace(" ","_"),
            "commence_time":board.get("startTime"),"home_team":board.get("participant1Name",""),
            "away_team":board.get("participant2Name",""),"market_id":mid,"outcome_ids":{v:k for k,v in name_for_id.items()},
            "bookmakers":books}
def score_ledger_for_finished(data,key,history,now,stamp):
    # Exactly one older fixture graded at most once daily; no assumed results.
    day=now().strftime("%Y-%m-%d")
    if data.get("papi_settlement_day")==day or now().day%2==0:return  # preserve free API allowance
    pending=sorted((h for h in history if h.get("settled") is None and h.get("outcome_id") and
                   (p:=__import__("datetime").datetime.fromisoformat(h["start"].replace("Z","+00:00")))<now()-dt.timedelta(hours=4)),
                   key=lambda h:h["start"])
    if not pending:return
    sample=pending[0]
    result=call(data,key,"settlements",{"fixtureId":sample["event_id"]})
    markets=result.get("markets") or {}
    done=False
    for h in history:
        if h.get("event_id")!=sample["event_id"] or h.get("settled") is not None:continue
        player=(((markets.get(str(h.get("market_id"))) or {}).get("outcomes") or {}).get(str(h["outcome_id"])) or {}).get("players",{}).get("0",{})
        status=player.get("result")
        if status in ("WIN","LOSE"):
            h["settled"]=1 if status=="WIN" else 0;h["settled_at"]=stamp();done=True
    if done: data["papi_settlement_day"]=day
def collect(data,history,key,event_rows,now,stamp):
    data["source"]="OddsPapi v4, third-party bet365-labelled prices (one event per four-hour cycle; not all sports)"
    data["candidates"]=[];data["watchlist"]=[];data["source_sports"]=[];data["scanned_events"]=0
    issues=[]
    day=now().strftime("%Y-%m-%d")
    cache=data.get("papi_fixtures",[])
    if data.get("papi_fixtures_day")!=day or not cache:
        try:
            fixtures=call(data,key,"fixtures",{"from":stamp(now()),"to":stamp(now()+dt.timedelta(hours=36)),
                "statusId":0,"hasOdds":"true","bookmakers":"bet365"})
            if not isinstance(fixtures,list):raise ValueError("Unexpected fixture response type")
            fixtures=[x for x in fixtures if x.get("fixtureId") and x.get("hasOdds")]
            # Store only small, public schedule metadata; no provider raw odds.
            cache=[{k:x.get(k) for k in ("fixtureId","sportId","sportName","startTime","participant1Name","participant2Name","tournamentName")}
                   for x in fixtures[:1200]]
            data["papi_fixtures"]=cache;data["papi_fixtures_day"]=day
        except Exception as exc:issues.append("Fixture discovery failed: "+type(exc).__name__)
    month=now().strftime("%Y-%m")
    if data.get("papi_markets_month")!=month or not data.get("papi_markets"):
        try:
            all_markets=call(data,key,"markets",{"language":"en"})
            if not isinstance(all_markets,list):raise ValueError("Unexpected market catalogue")
            # Retain only full-match winner metadata; no arbitrary market-ID guesses.
            kept=[m for m in all_markets if eligible_market(m,m.get("sportId",0))]
            data["papi_markets"]=kept
            data["papi_markets_month"]=month
        except Exception as exc:issues.append("Market catalogue unavailable: "+type(exc).__name__)
    recent=data.setdefault("papi_last_polled",{})
    recent={k:v for k,v in recent.items() if v and (now()-dt.datetime.fromisoformat(v.replace("Z","+00:00")))<dt.timedelta(days=3)}
    data["papi_last_polled"]=recent
    eligible=[]
    for f in cache:
        try: start=dt.datetime.fromisoformat(f["startTime"].replace("Z","+00:00"))
        except (TypeError,ValueError,AttributeError):continue
        if not now()+dt.timedelta(minutes=35)<start<now()+dt.timedelta(hours=36):continue
        sportid=f.get("sportId") or 999
        distance=(start-now()).total_seconds()/3600
        last=recent.get(f["fixtureId"])
        stale=not last or (now()-dt.datetime.fromisoformat(last.replace("Z","+00:00"))).total_seconds()/3600>12
        if not stale:continue
        recent_count=sum(1 for other in cache if other.get("sportId")==sportid and other.get("fixtureId") in recent)
        eligible.append((recent_count,FOCUS.get(sportid,20),abs(distance-7),start,f))
    eligible.sort(key=lambda r:r[:4])
    if eligible:
        f=eligible[0][4]
        try:
            opts={"fixtureId":f["fixtureId"],"oddsFormat":"decimal","language":"en"}
            if COMPARATORS: opts["bookmakers"]=COMPARATORS
            board=call(data,key,"odds",opts)
            normalized=normalize(board,data.get('papi_markets',[]))
            recent[f["fixtureId"]]=stamp()
            if normalized:
                rows=event_rows(normalized,history)
                data["candidates"]=sorted([r for r in rows if r["status"]=="BET_CANDIDATE"],key=lambda r:-r["conservative_ev"])[:3]
                data["watchlist"]=sorted([r for r in rows if r["status"]=="WATCH"],key=lambda r:-r["lower_probability"])[:30]
                data["source_sports"]=[normalized["sport_key"]]
                data["scanned_events"]=1
                # Per-fixture refs needed to grade the outcome by its immutable market/outcome IDs.
                for h in history:
                    if h.get("event_id")==normalized["id"] and h.get("outcome_id") is None:
                        h["market_id"]=normalized["market_id"]
                        h["outcome_id"]=normalized["outcome_ids"].get(h["selection"])
                if not rows:issues.append("Selected fixture has no complete independently comparable moneyline.")
            else:issues.append("Selected fixture has no safely parsed Winner market.")
        except Exception as exc:issues.append("Odds collection failed: "+type(exc).__name__)
    else:issues.append("No unpolled qualifying future fixtures in today's capped discovery set.")
    try:score_ledger_for_finished(data,key,history,now,stamp)
    except Exception as exc:issues.append("Settlement check deferred: "+type(exc).__name__)
    # Do not call an odds cycle complete if it had no verified eligible price rows.
    data["source_status"]="OK" if data["scanned_events"] and not issues else "PARTIAL" if data["scanned_events"] else "ERROR"
    if data["source_status"]=="OK":data["last_success"]=stamp()
    if data["source_status"]!="OK":
        data["candidates"]=[] # Fail closed on any incomplete source state.
    data["quota_remaining"]=max(0,MAX_MONTHLY_CALLS-data.get("papi_usage",{}).get("count",0))
    data["messages"]=issues or ["Bet365-labelled odds are provider observations, not authenticated offers in your account."]
    if not data["candidates"]:data["messages"].append("NO APPROVED BET — model and price gates did not both pass.")
