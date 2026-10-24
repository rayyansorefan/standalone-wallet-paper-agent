"""Strict OddsPapi spending limits, with an unmetered account check."""
import datetime as dt
import json
import urllib.parse
import urllib.request

MONTHLY_SOFT_LIMIT = 220  # For a 250-call subscription: 30 requests in reserve.
BASE = "https://api.oddspapi.io/v4/"

def check_quota(data, key):
    """Fail closed unless the real subscription usage and bet365 entitlement are known."""
    q = urllib.parse.urlencode({"apiKey": key})
    req = urllib.request.Request(BASE+"account?"+q, headers={"Accept":"application/json"})
    with urllib.request.urlopen(req, timeout=18) as response:
        account = json.load(response)
    subs = account.get("subscriptions") or []
    active = next((s for s in subs if s.get("is_active") and s.get("subscription_id")==account.get("current_subscription_id")), None)
    if not active: active = next((s for s in subs if s.get("is_active")), None)
    if not active: raise RuntimeError("No active OddsPapi subscription")
    limit, count = int(active["request_limit"]), int(active["request_count"])
    cap = min(MONTHLY_SOFT_LIMIT, max(0,limit-30))
    usage = {"count":count,"provider_limit":limit,"hard_cap":cap,"reserved":limit-cap,"checked_at":dt.datetime.now(dt.timezone.utc).isoformat()}
    data["papi_usage"] = usage
    data["quota_remaining"] = max(0,cap-count)
    if "bet365" not in (active.get("bookmakers") or {}):
        raise RuntimeError("Subscription does not permit bet365 research")
    if count >= cap: raise RuntimeError("Monthly soft cap reached; reserve protected")
    return usage

def billable_call(data, key, path, params):
    """Every attempted billable endpoint call consumes one budget unit, including errors."""
    usage=data.get("papi_usage") or {}
    if "hard_cap" not in usage: raise RuntimeError("No verified account quota; no API calls allowed")
    if usage["count"]>=usage["hard_cap"]: raise RuntimeError("Quota exhausted; call blocked")
    usage["count"]+=1
    data["quota_remaining"]=max(0,usage["hard_cap"]-usage["count"])
    query=urllib.parse.urlencode({**params,"apiKey":key})
    req=urllib.request.Request(BASE+path+"?"+query,headers={"Accept":"application/json","User-Agent":"BookieResearchHub/1.0"})
    with urllib.request.urlopen(req,timeout=25) as response:
        value=json.load(response)
    if isinstance(value,dict) and value.get("error"):raise RuntimeError("Odds provider returned an error")
    return value
