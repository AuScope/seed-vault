"""FDSN client construction, including user-defined per-service URLs.

A client in ``clients.csv`` may optionally define its own ``dataselect``,
``event`` and ``station`` URLs (e.g. ``https://host/custom/quakes/1``). Each
column is either

* empty  – use the standard path under the base URL (``<base>/fdsnws/<service>/1``)
* a URL  – use this address for the service
* ``none`` – this client does not offer the service

All backend code should create clients with :func:`make_client` so these
mappings are honoured.
"""
import copy
import socket
import threading
import time
from collections import Counter
from email.utils import parsedate_to_datetime
from typing import Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from obspy.clients.fdsn import Client
from obspy.clients.fdsn.client import WADLParser, download_url
from obspy.clients.fdsn.header import DEFAULT_SERVICES, FDSNException, FDSNNoDataException

SERVICES = ("dataselect", "event", "station")
DISABLED = "none"
USER_AGENT = "SEED-Vault"

# --------------------------------------------------------------------------
# HTTP 429 (Too Many Requests) handling
#
# A 429 means "wait", not "retry now": requests sent before the server's
# Retry-After has passed are refused again. ObsPy discards response headers
# (and doesn't retry), so we wrap the client's urllib opener: on a 429 it waits
# max(Retry-After, MIN_429_WAIT) and then retries. The deadline is shared per
# host, so every other request to that server - other clients, discovery
# threads - holds off as well.
# --------------------------------------------------------------------------
MIN_429_WAIT = 60.0          # seconds; never retry sooner than this
MAX_429_WAIT = 3600.0        # a server asking for longer than this: give up on the request
MAX_429_RETRIES = 5

_host_lock = threading.Lock()
_host_not_before: Dict[str, float] = {}


class DownloadCancelled(Exception):
    """Raised when the user cancels while a request is waiting out a 429."""


def parse_retry_after(value: Optional[str], now: Optional[float] = None) -> Optional[float]:
    """Seconds to wait from a Retry-After header (delay-seconds or HTTP-date)."""
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    return max(0.0, when - (time.time() if now is None else now))


def _wait_until(deadline: float, stop_event: Optional[threading.Event]):
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        if stop_event is not None:
            if stop_event.wait(min(remaining, 1.0)):
                raise DownloadCancelled("Cancelled while waiting for the server's rate limit to reset")
        else:
            time.sleep(min(remaining, 1.0))


def _host_of(request) -> str:
    url = getattr(request, "full_url", request)
    try:
        return urlparse(str(url)).netloc.lower()
    except Exception:
        return ""


def _fmt_wait(seconds: float) -> str:
    return f"{seconds:.0f} s" if seconds < 120 else f"{seconds / 60:.1f} min"


class RateLimitedOpener:
    """Wraps a urllib OpenerDirector so HTTP 429 responses are waited out, honouring Retry-After."""

    def __init__(self, opener, owner):
        self._opener = opener
        self._owner = owner

    def open(self, request, *args, **kwargs):
        host = _host_of(request)
        attempt = 0
        while True:
            with _host_lock:
                not_before = _host_not_before.get(host, 0.0)
            _wait_until(not_before, getattr(self._owner, "stop_event", None))
            try:
                return self._opener.open(request, *args, **kwargs)
            except HTTPError as e:
                if e.code != 429:
                    raise
                retry_after = parse_retry_after(e.headers.get("Retry-After") if e.headers else None)
                wait = max(MIN_429_WAIT, retry_after or 0.0)
                if attempt >= MAX_429_RETRIES or wait > MAX_429_WAIT:
                    print(f"      ! {host}: HTTP 429 Too Many Requests – giving up on this request "
                          f"(server asked to wait {_fmt_wait(wait)}"
                          f"{'' if attempt < MAX_429_RETRIES else f' after {attempt} retries'}).")
                    raise
                attempt += 1
                with _host_lock:
                    _host_not_before[host] = max(_host_not_before.get(host, 0.0), time.time() + wait)
                source = "Retry-After" if retry_after is not None else "no Retry-After header"
                print(f"      ⏳ {host}: HTTP 429 Too Many Requests – waiting {_fmt_wait(wait)} "
                      f"({source}; minimum {MIN_429_WAIT:.0f} s) before retry {attempt}/{MAX_429_RETRIES}")
                try:
                    e.close()
                except Exception:
                    pass

    def __getattr__(self, name):
        return getattr(self._opener, name)


def _is_empty_body(data) -> bool:
    if data is None:
        return True
    if isinstance(data, (bytes, bytearray, str)):
        return len(data) == 0
    getbuffer = getattr(data, "getbuffer", None)
    if getbuffer is not None:
        try:
            return getbuffer().nbytes == 0
        except Exception:
            return False
    return False


class SeedVaultClient(Client):
    """ObsPy FDSN client whose HTTP requests wait out 429 responses (see RateLimitedOpener).

    Set ``client.stop_event`` (a threading.Event) to make those waits cancellable.
    """
    stop_event: Optional[threading.Event] = None

    def _set_opener(self, user, password):
        super()._set_opener(user, password)
        if not isinstance(self._url_opener, RateLimitedOpener):
            self._url_opener = RateLimitedOpener(self._url_opener, self)

    def _download(self, url, *args, **kwargs):
        """Some servers (e.g. EPOSFR) answer "no data" with HTTP 200 and an empty body
        instead of 204. ObsPy only recognises 204, then fails trying to parse zero
        bytes as miniSEED. Treat an empty successful response as "no data"."""
        data = super()._download(url, *args, **kwargs)
        if _is_empty_body(data):
            raise FDSNNoDataException("No data available for request (HTTP 200 with an empty body).")
        return data


# --------------------------------------------------------------------------
# Error classification (so runs can report *what kind* of failures happened)
# --------------------------------------------------------------------------
_STATUS_LABELS = {
    204: "204 No data", 400: "400 Bad request", 401: "401 Unauthorized", 403: "403 Forbidden",
    404: "404 Not found", 413: "413 Request too large", 414: "414 URL too long",
    429: "429 Too many requests", 500: "500 Server error", 502: "502 Bad gateway",
    503: "503 Service unavailable", 504: "504 Gateway timeout",
}


def classify_error(exc: BaseException) -> str:
    """A short, stable label for a download error, e.g. "429 Too many requests"."""
    if isinstance(exc, DownloadCancelled):
        return "Cancelled"
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if code is None and isinstance(exc, FDSNException):
        text = str(exc)
        for c in _STATUS_LABELS:
            if f"code: {c}" in text or f"Status code: {c}" in text:
                code = c
                break
    if isinstance(code, int):
        return _STATUS_LABELS.get(code, f"{code} HTTP error")
    name = type(exc).__name__
    if isinstance(exc, (socket.timeout, TimeoutError)) or "Timeout" in name or "timed out" in str(exc):
        return "Timeout"
    if isinstance(exc, (URLError, ConnectionError)) or "NoService" in name:
        return "Connection error"
    return name


class ErrorTally:
    """Counts download errors by type for an end-of-run summary."""

    def __init__(self):
        self.counts: Counter = Counter()
        self.examples: Dict[str, str] = {}

    def record(self, exc: BaseException, context: str = "") -> str:
        label = classify_error(exc)
        self.counts[label] += 1
        self.examples.setdefault(label, context)
        return label

    def summary(self) -> str:
        if not self.counts:
            return "No download errors."
        parts = [f"{label} ×{n}" for label, n in self.counts.most_common()]
        return "Download errors by type: " + ", ".join(parts)

    def __bool__(self):
        return bool(self.counts)


class MappedClient(SeedVaultClient):
    """ObsPy Client whose service discovery copes with non-standard addresses.

    ObsPy decides which service a WADL belongs to by looking for the words
    "dataselect"/"event"/"station" in its URL, so a custom address such as
    ``https://host/api/quakes/1`` would silently be treated as missing. Here
    each service is probed at its own address; if a custom endpoint publishes
    no WADL it is still trusted (with the standard FDSN parameter set), since
    the user configured it explicitly.
    """

    def _discover_services(self):
        self.services = {}
        for service in SERVICES:
            if service in self._service_mappings and self._service_mappings[service] is None:
                continue  # deliberately disabled
            url = self._build_url(service, "application.wadl")
            params = None
            try:
                code, data = download_url(url, opener=self._url_opener, headers=self.request_headers,
                                          timeout=min(self.timeout, 30), debug=self.debug)
                if code == 200 and data:
                    params = WADLParser(data).parameters
            except Exception as e:  # noqa: BLE001 – unreachable WADL is not fatal for custom endpoints
                if self.debug:
                    print(f"Could not read WADL for {service} at {url}: {e}")
            if params is None and service in self._service_mappings:
                params = copy.deepcopy(DEFAULT_SERVICES[service])
            if params is not None:
                self.services[service] = params


def _clean(value) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    return "" if value.lower() == "nan" else value


def service_mappings_from_row(row: dict) -> Dict[str, Optional[str]]:
    """``{'event': 'https://…', 'station': None}`` from a clients.csv row (only non-default entries)."""
    out: Dict[str, Optional[str]] = {}
    for service in SERVICES:
        v = _clean(row.get(service))
        if not v:
            continue
        out[service] = None if v.lower() == DISABLED else v.rstrip("/")
    return out


def base_url_for(base_url: str, mappings: Dict[str, Optional[str]]) -> str:
    """ObsPy needs a base URL; if none was given, derive one from the first custom service URL."""
    base_url = _clean(base_url)
    if base_url:
        return base_url
    for v in mappings.values():
        if v:
            p = urlparse(v)
            return f"{p.scheme}://{p.netloc}"
    raise ValueError("A client needs a base URL or at least one service URL.")


def build_client(base_url: str, service_mappings: Optional[Dict[str, Optional[str]]] = None,
                 user_agent: str = USER_AGENT, **kwargs) -> Client:
    """Create an ObsPy client for a base URL (or ObsPy shortcut) and optional per-service URLs."""
    if service_mappings:
        return MappedClient(base_url_for(base_url, service_mappings), service_mappings=dict(service_mappings),
                            user_agent=user_agent, **kwargs)
    return SeedVaultClient(base_url, user_agent=user_agent, **kwargs)


def _client_row(name: str) -> Optional[dict]:
    """Look up a client in clients.csv (read fresh: it is small and may have just been edited)."""
    import pandas as pd
    from seed_vault.models.url_mapping import UrlMappings
    try:
        df = pd.read_csv(UrlMappings().save_path, dtype=str, keep_default_na=False)
    except Exception:
        return None
    match = df[df["client"].str.upper() == str(name).upper()]
    return match.iloc[0].to_dict() if len(match) else None


def make_client(name: str, user_agent: str = USER_AGENT, **kwargs) -> Client:
    """Create a client from a configured name, honouring custom service URLs.

    Extra keyword arguments (``user``, ``password``, ``timeout``…) go to ObsPy.
    """
    row = _client_row(name)
    if row is not None:
        mappings = service_mappings_from_row(row)
        if mappings:
            return build_client(row.get("url", ""), mappings, user_agent=user_agent, **kwargs)
        url = _clean(row.get("url"))
        if url and str(row.get("is_original", "")).lower() != "true":
            return SeedVaultClient(url, user_agent=user_agent, **kwargs)
    return SeedVaultClient(name, user_agent=user_agent, **kwargs)


def available_services(client: Client) -> Dict[str, bool]:
    return {s: s in client.services for s in ("station", "event", "dataselect")}
