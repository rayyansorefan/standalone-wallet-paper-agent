"""Fail-closed token screening with distinct rejection and provider-health outcomes.

No API response, corrupted data or HTTP error can authorise any trade.
"""
import http.client
import ipaddress
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
RUGCHECK_HOST = "api.rugcheck.xyz"
DOH_RESOLVERS = (
    ("cloudflare-dns.com", "/dns-query", ("1.1.1.1", "1.0.0.1"), {}),
    ("dns.google", "/resolve", ("8.8.8.8", "8.8.4.4"),
     {"edns_client_subnet": "0.0.0.0/0"}),
)
TRANSPORT_KEY = "_paper_agent_security_transport"


def result(status, reason, score=None, http_status=None, failure_kind=None,
           provider_transport=None, provider_stage=None):
    return {"status": status, "allowed": status == "PASS", "reason": reason,
            "score_normalised": score, "http_status": http_status,
            "failure_kind": failure_kind,
            "provider_transport": provider_transport,
            "provider_stage": provider_stage}


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


def _resolve_current_ipv4(host):
    last_error = None
    for resolver_host, resolver_path, bootstrap_addresses, extra_query in DOH_RESOLVERS:
        query = urllib.parse.urlencode(
            {"name": host, "type": "A", **extra_query})
        path = resolver_path + "?" + query
        if resolver_host == "dns.google":
            try:
                req = urllib.request.Request(
                    "https://" + resolver_host + path, headers={
                        "Accept": "application/dns-json",
                        "User-Agent": "PaperAgentResearch/1.1"})
                with urllib.request.urlopen(req, timeout=4) as response:
                    address = _public_ipv4_from_doh(json.load(response))
                if address:
                    return address
            except Exception as exc:
                last_error = exc
        for bootstrap_address in bootstrap_addresses:
            try:
                payload = _fetch_json_at_address(
                    resolver_host, path, bootstrap_address, timeout=4,
                    accept="application/dns-json")
                return _public_ipv4_from_doh(payload)
            except Exception as exc:
                last_error = exc
    raise last_error


def _public_ipv4_from_doh(payload):
    if not isinstance(payload, dict) or payload.get("Status") != 0:
        raise ValueError("DNS-over-HTTPS response was not successful")
    for answer in payload.get("Answer", []):
        if not isinstance(answer, dict) or answer.get("type") != 1:
            continue
        try:
            address = ipaddress.ip_address(answer.get("data", ""))
        except ValueError:
            continue
        if address.version == 4 and address.is_global:
            return str(address)
    raise urllib.error.URLError(socket.gaierror(
        socket.EAI_NONAME, "No public A record from DNS-over-HTTPS"))


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a fresh DoH address while verifying the official hostname."""
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self._resolved_address = address

    def connect(self):
        sock = socket.create_connection(
            (self._resolved_address, self.port), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _fetch_json_at_address(host, path, address, timeout, accept="application/json"):
    connection = _PinnedHTTPSConnection(host, address, timeout=timeout)
    url = "https://" + host + path
    try:
        connection.request("GET", path, headers={
            "Accept": accept, "Host": host,
            "User-Agent": "PaperAgentResearch/1.1"})
        response = connection.getresponse()
        if response.status < 200 or response.status >= 300:
            raise urllib.error.HTTPError(
                url, response.status, "HTTPS endpoint returned an error",
                response.headers, None)
        return json.load(response)
    finally:
        connection.close()


def _fetch_summary_at_address(path, address):
    payload = _fetch_json_at_address(
        RUGCHECK_HOST, path, address, timeout=12)
    if isinstance(payload, dict):
        payload = dict(payload)
        payload[TRANSPORT_KEY] = "doh_bootstrap_tls"
    return payload


def fetch_summary(mint):
    path = "/v1/tokens/" + urllib.parse.quote(mint, safe="") + "/report/summary"
    url = "https://" + RUGCHECK_HOST + path
    req = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": "PaperAgentResearch/1.1"})
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            return json.load(response)
    except urllib.error.URLError as exc:
        if classify_failure(exc) != "dns_error":
            raise
        # Fresh public DNS evidence only; never reuse a cached/stale address.
        # The fallback still verifies RugCheck's ordinary TLS certificate/SNI.
        try:
            address = _resolve_current_ipv4(RUGCHECK_HOST)
        except Exception as fallback_exc:
            # Bounded provenance only; never persist exception text.
            fallback_exc.provider_transport = "doh_bootstrap_tls"
            fallback_exc.provider_stage = "doh_resolve"
            raise
        try:
            return _fetch_summary_at_address(path, address)
        except Exception as fallback_exc:
            fallback_exc.provider_transport = "doh_bootstrap_tls"
            fallback_exc.provider_stage = "rugcheck_summary"
            raise


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
                      http_status=exc.code, failure_kind=classify_failure(exc),
                      provider_transport=getattr(exc, "provider_transport", None),
                      provider_stage=getattr(exc, "provider_stage", None))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return result("UNAVAILABLE", "security API request or JSON failed",
                      failure_kind=classify_failure(exc),
                      provider_transport=getattr(exc, "provider_transport", None),
                      provider_stage=getattr(exc, "provider_stage", None))
    except Exception as exc:
        return result("UNAVAILABLE", "security API unexpected error",
                      failure_kind=classify_failure(exc),
                      provider_transport=getattr(exc, "provider_transport", None),
                      provider_stage=getattr(exc, "provider_stage", None))
    transport = payload.get(TRANSPORT_KEY) if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or not isinstance(payload.get("risks"), list):
        return result("UNAVAILABLE", "security report missing risk list",
                      provider_transport=transport)
    try:
        score = float(payload.get("score_normalised"))
    except (ValueError, TypeError, OverflowError):
        return result("UNAVAILABLE", "security report missing normalized risk score",
                      provider_transport=transport)
    if not math.isfinite(score) or score < 0 or score > 100:
        return result("UNAVAILABLE", "normalized risk score outside documented range",
                      provider_transport=transport)
    if score > 25:
        return result("REJECTED", "normalized risk score above 25", score=score,
                      provider_transport=transport)
    for risk in payload["risks"]:
        if not isinstance(risk, dict):
            return result("UNAVAILABLE", "malformed security risk entry", score=score,
                          provider_transport=transport)
        if str(risk.get("level", "")).lower() in BLOCKED_LEVELS:
            return result("REJECTED", "severe security flag", score=score,
                          provider_transport=transport)
        name = str(risk.get("name", "")).lower()
        if any(word in name for word in BLOCKED_NAMES):
            return result("REJECTED", "dangerous mint, freeze or sellability flag",
                          score=score, provider_transport=transport)
    return result("PASS", "risk score and flags pass provisional screen", score=score,
                  provider_transport=transport)


def screen_token(mint):
    """Backwards-compatible bool API: unverified or rejected always False."""
    return inspect_token(mint)["allowed"]
