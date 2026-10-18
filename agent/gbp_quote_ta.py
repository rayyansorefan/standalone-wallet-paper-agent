"""Independent quote-derived technical-analysis research. PAPER ONLY, zero orders/API calls.

These are sampled pool mid/spot quotes, NOT exchange OHLC candles or executable
fills. Never backfill RSI/MACD from stale marks, and never promote an arm.
"""
import datetime as dt
import hashlib
import json
import math

KEY = "gbp_quote_ta_v1"
VERSION = "GBP_QUOTE_TA_FROZEN_1"
HORIZONS = (5, 30, 60)
MAX_SERIES = 100
MAX_MARKS = 48
MAX_PENDING = 180
MAX_DONE = 900
MAX_ADMISSIONS_CYCLE = 10
MAX_GAP_SECONDS = 8 * 60
RULES = {
    "sampled_quote_control": "every fully featured pool, long-spot quote return",
    "ema_macd_continuation": "EMA12>EMA26, MACD>signal9, RSI14 50..70, m5 0.2..2.5%",
    "observed_high_breakout": "above prior 20 observed marks, RSI14 55..80, MACD>signal9",
    "oversold_reversion": "RSI14 20..35, close<EMA26, m5<0",
}
DIGEST = hashlib.sha256(json.dumps(
    [VERSION, RULES, HORIZONS, "1pct_each_side", "extra_2pct_stress",
     "no_trades_no_auto_promotion"], sort_keys=True).encode()).hexdigest()


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def ema(values, span):
    factor = 2 / (span + 1)
    out = float(values[0])
    for value in values[1:]:
        out += factor * (value - out)
    return out


def indicator_snapshot(prices):
    """Only computed after 35 CONTIGUOUS five-minute observed quotes."""
    if len(prices) < 35:
        return None
    values = [finite(x) for x in prices]
    if any(x is None or x <= 0 for x in values):
        return None
    change = [(v - prev) / prev * 100 for prev, v in zip(values, values[1:])]
    gains = sum(max(x, 0) for x in change[-14:]) / 14
    losses = -sum(min(x, 0) for x in change[-14:]) / 14
    rsi = 100 if losses == 0 else 100 - 100 / (1 + gains / losses)
    macds = []
    for end in range(26, len(values) + 1):
        prior = values[:end]
        macds.append(ema(prior, 12) - ema(prior, 26))
    if len(macds) < 9:
        return None
    macd_signal = ema(macds, 9)
    return dict(
        rsi14=rsi, ema12=ema(values, 12), ema26=ema(values, 26),
        macd=macds[-1], macd_signal9=macd_signal,
        change_5m_pct=change[-1], previous_20_mark_high=max(values[-21:-1]),
        close=values[-1], marks=len(values),
    )


def select_arms(f):
    price = f["close"]
    macd_up = f["macd"] > f["macd_signal9"]
    result = ["sampled_quote_control"]
    if (f["ema12"] > f["ema26"] and macd_up and
            50 <= f["rsi14"] <= 70 and .2 <= f["change_5m_pct"] <= 2.5):
        result.append("ema_macd_continuation")
    if (price > f["previous_20_mark_high"] and macd_up and
            55 <= f["rsi14"] <= 80):
        result.append("observed_high_breakout")
    if (20 <= f["rsi14"] <= 35 and price < f["ema26"] and
            f["change_5m_pct"] < 0):
        result.append("oversold_reversion")
    return result


def _summary(book, arm, horizon):
    rows = [r for r in book["done"] + book["pending"] if arm in r["arms"]]
    label = str(horizon) + "m"
    priced = [(r, r["outcomes"][label]["net_quote_roi_pct"])
              for r in rows if label in r["outcomes"] and
              finite(r["outcomes"][label].get("net_quote_roi_pct")) is not None]
    missing = sum(label in r["outcomes"] and
                  finite(r["outcomes"][label].get("net_quote_roi_pct")) is None
                  for r in rows)
    pending = len(rows) - missing - len(priced)
    vals = [v for _, v in priced]
    return dict(
        selected=len(rows), priced=len(vals), missing=missing, pending=pending,
        wins=sum(v > 0 for v in vals), losses=sum(v < 0 for v in vals),
        mean_net_quote_roi_pct=round(sum(vals) / len(vals), 4) if vals else None,
        mean_stressed_quote_roi_pct=round(sum(v - 2 for v in vals) / len(vals), 4)
            if vals else None,
        distinct_pools=len({r["pool"] for r, _ in priced}),
        distinct_days=len({r["at"][:10] for r, _ in priced}),
        review_ready=False, trades_enabled=False,
    )


def update(state, fresh_prices, current):
    """Research-only; prices must be already-fetched fresh quotes from core."""
    if current.tzinfo is None:
        raise ValueError("UTC-aware current required")
    research = state.setdefault("research", {})
    book = research.setdefault(KEY, {
        "version": VERSION, "hypothesis_sha256": DIGEST,
        "registered_at": current.isoformat(), "cycles": 0,
        "status": "COLLECTING_UNPROVEN", "automatic_promotion": False,
        "paper_entries_allowed": False, "marks": {}, "pending": [], "done": [],
        "last_admission": {}, "reset_gaps": 0, "total_marks": 0,
    })
    if book.get("version") != VERSION or book.get("hypothesis_sha256") != DIGEST:
        book["status"] = "INVALIDATED_SOURCE_CHANGED"
        book["automatic_promotion"] = False
        return book
    if book.get("last_run") and current.isoformat() <= book["last_run"]:
        return book
    quotes = {pool:price for pool, raw in (fresh_prices or {}).items()
              if isinstance(pool, str) and (price := finite(raw)) is not None
              and price > 0}
    # First settle outcomes using this cycle's new observations, never past prices.
    for row in list(book["pending"]):
        start = dt.datetime.fromisoformat(row["at"])
        age = (current - start).total_seconds()
        for horizon in HORIZONS:
            label = str(horizon) + "m"
            if label in row["outcomes"] or age < horizon * 60:
                continue
            p = quotes.get(row["pool"])
            if age <= horizon * 60 + 600 and p is not None:
                net = 100 * (p / row["entry_price"] * .99 / 1.01 - 1)
                row["outcomes"][label] = {"net_quote_roi_pct": round(net, 5),
                                          "at": current.isoformat()}
            elif age > horizon * 60 + 600:
                row["outcomes"][label] = {"status": "MISSING_FRESH_MARK"}
        if len(row["outcomes"]) == len(HORIZONS):
            book["done"].append(row)
            book["pending"].remove(row)
    book["done"] = book["done"][-MAX_DONE:]
    tick = int(current.timestamp()) // 300
    candidates = []
    for pool in sorted(quotes):
        s = book["marks"].setdefault(pool, [])
        if s:
            prev = dt.datetime.fromisoformat(s[-1]["at"])
            elapsed = (current - prev).total_seconds()
            if elapsed <= 0 or int(prev.timestamp()) // 300 == tick:
                continue
            if elapsed > MAX_GAP_SECONDS:
                s.clear()   # never join distant observations as continuous bars
                book["reset_gaps"] += 1
        s.append({"at": current.isoformat(), "price": quotes[pool]})
        del s[:-MAX_MARKS]
        book["total_marks"] += 1
        features = indicator_snapshot([a["price"] for a in s])
        if features is None:
            continue
        previous = book["last_admission"].get(pool)
        if previous:
            then = dt.datetime.fromisoformat(previous)
            if (current - then).total_seconds() < 3600:
                continue
        candidates.append((pool, features))
    # Memory is bounded and deterministic, preserving most recently refreshed pools.
    if len(book["marks"]) > MAX_SERIES:
        keep = sorted(book["marks"], key=lambda p:book["marks"][p][-1]["at"],
                      reverse=True)[:MAX_SERIES]
        book["marks"] = {p:book["marks"][p] for p in keep}
    # Rotate amongst simultaneous qualifying pools to avoid alphabetic selection bias.
    candidates.sort(key=lambda a:hashlib.sha256(
        (a[0]+str(tick)).encode()).hexdigest())
    for pool, features in candidates[:min(MAX_ADMISSIONS_CYCLE,
                                         max(0, MAX_PENDING-len(book["pending"])))]:
        book["pending"].append(dict(
            at=current.isoformat(), pool=pool, entry_price=quotes[pool],
            arms=select_arms(features), features=features, outcomes={}))
        book["last_admission"][pool] = current.isoformat()
    # Keep admissions map bounded by hour; never affects accounts or entries.
    book["last_admission"] = {
        p:at for p,at in book["last_admission"].items()
        if 0 <= (current-dt.datetime.fromisoformat(at)).total_seconds() < 3600}
    book["cycles"] += 1
    book["last_run"] = current.isoformat()
    book["status"] = "COLLECTING_UNPROVEN"
    book["automatic_promotion"] = False
    book["reports"] = {arm:{str(h)+"m":_summary(book,arm,h) for h in HORIZONS}
                       for arm in RULES}
    book["evidence_note"] = (
        "Polled spot quotes, NOT OHLC candles or executable fills. Fixed indicator "
        "hypotheses, 1% per-side cost + 2pp stress, distinct pool/day caution. "
        "No actual trades, risk gate changes, or automatic strategy promotion.")
    return book


def safe_update(state, fresh_prices, current):
    try:
        return update(state, fresh_prices, current)
    except Exception as exc:
        record = state.setdefault("research", {}).setdefault(KEY, {})
        record["status"] = "RESEARCH_ERROR"
        record["error_type"] = type(exc).__name__
        record["automatic_promotion"] = False
        return record
