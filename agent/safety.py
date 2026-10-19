"""Fail-closed token screening with distinct rejection and provider-health outcomes.

No API response, corrupted data or HTTP error can authorise any trade.
"""
import json
import math
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
BLOCKED_LEVELS = {"high", "danger", "critical"}
BLOCKED_NAMES = ("mint authority", "freeze authority", "cannot sell", "honeypot")


def result(status, reason, score=None, http_status=None, failure_kind=None):
    return {"status": status, "allowed": status == "PASS", "reason": reason,
            "score_normalised": score, "http_status": http_status,
            "failure_kind": failure_kind}


def classify_failure(exc):
    """Return a bounded provider diagnostic without persisting exception text."""
    if isinstance(exc, urllib.error.HTTPError):
        return "http_error"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "timeout"
        if isinstance(reason, ssl.SSLError):
            return "tls_error"
        if isinstance(reason, socket.gaierror):
            return "dns_error"
        return "url_error"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return "invalid_json"
    if isinstance(exc, OSError):
        return "os_error"
    if isinstance(exc, ValueError):
        return "invalid_json"
    return "unexpected_error"


def fetch_summary(mint):
    url = "https://api.rugcheck.xyz/v1/tokens/" + urllib.parse.quote(mint, safe="") + "/report/summary"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": "PaperAgentResearch/1.1"})
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.load(response)


def inspect_token(mint, fetch=None):
    """Return PASS, REJECTED or UNAVAILABLE with an auditable explanation.

    The injectable fetch callable permits deterministic tests without the network.
    """
    if not isinstance(mint, str) or not ADDRESS.fullmatch(mint):
        return result("REJECTED", "invalid Solana token mint")
    try:
        payload = (fetch or fetch_summary)(mint)
    except urllib.error.HTTPError as exc:
        return result("UNAVAILABLE", "security API HTTP error",
                      http_status=exc.code, failure_kind=classify_failure(exc))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return result("UNAVAILABLE", "security API request or JSON failed",
                      failure_kind=classify_failure(exc))
    except Exception as exc:
        return result("UNAVAILABLE", "security API unexpected error",
                      failure_kind=classify_failure(exc))
    if not isinstance(payload, dict) or not isinstance(payload.get("risks"), list):
        return result("UNAVAILABLE", "security report missing risk list")
    try:
        score = float(payload.get("score_normalised"))
    except (ValueError, TypeError, OverflowError):
        return result("UNAVAILABLE", "security report missing normalized risk score")
    if not math.isfinite(score) or score < 0 or score > 100:
        return result("UNAVAILABLE", "normalized risk score outside documented range")
    if score > 25:
        return result("REJECTED", "normalized risk score above 25", score=score)
    for risk in payload["risks"]:
        if not isinstance(risk, dict):
            return result("UNAVAILABLE", "malformed security risk entry", score=score)
        if str(risk.get("level", "")).lower() in BLOCKED_LEVELS:
            return result("REJECTED", "severe security flag", score=score)
        name = str(risk.get("name", "")).lower()
        if any(word in name for word in BLOCKED_NAMES):
            return result("REJECTED", "dangerous mint, freeze or sellability flag", score=score)
    return result("PASS", "risk score and flags pass provisional screen", score=score)


def screen_token(mint):
    """Backwards-compatible bool API: unverified or rejected always False."""
    return inspect_token(mint)["allowed"]
