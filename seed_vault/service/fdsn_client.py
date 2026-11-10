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
from typing import Dict, Optional
from urllib.parse import urlparse

from obspy.clients.fdsn import Client
from obspy.clients.fdsn.client import WADLParser, download_url
from obspy.clients.fdsn.header import DEFAULT_SERVICES

SERVICES = ("dataselect", "event", "station")
DISABLED = "none"
USER_AGENT = "SEED-Vault"


class MappedClient(Client):
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
    return Client(base_url, user_agent=user_agent, **kwargs)


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
            return Client(url, user_agent=user_agent, **kwargs)
    return Client(name, user_agent=user_agent, **kwargs)


def available_services(client: Client) -> Dict[str, bool]:
    return {s: s in client.services for s in ("station", "event", "dataselect")}
