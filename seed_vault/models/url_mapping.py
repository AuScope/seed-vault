import os
import json

from pathlib import Path

from pydantic import BaseModel
from typing import List, Optional, Any
from obspy.clients.fdsn import Client
from obspy.clients.fdsn.header import URL_MAPPINGS
import pandas as pd

from seed_vault.enums.common import ClientType


current_directory = os.path.dirname(os.path.abspath(__file__))

# FDSN services that may be individually re-routed for servers with
# non-standard endpoint paths (see obspy Client(service_mappings=...)).
SERVICE_KEYS = ("station", "dataselect", "event")


def _normalize_service_url(url: Optional[str]) -> Optional[str]:
    """
    Normalize a per-service endpoint URL.

    ObsPy expects service mapping URLs *without* the trailing '/query'
    (e.g. 'http://arclink.ethz.ch/myfdsn/station/1'), so strip it if a
    user pastes the full query URL, along with any trailing slash.
    """
    if url is None or (isinstance(url, float) and pd.isna(url)) or str(url).strip() == "":
        return None
    url = str(url).strip().rstrip("/")
    if url.endswith("/query"):
        url = url[: -len("/query")]
    return url


class UrlMapping(BaseModel):
    """
    Represents a mapping between a seismic data client and its corresponding URL.

    Attributes:
        client (str): The name of the seismic data client.
        url (str): The associated base URL for retrieving seismic data.
        is_original (bool): Indicates whether the client is an original one from `URL_MAPPINGS`.
        station_url (Optional[str]): Override for the fdsnws 'station' service endpoint.
        dataselect_url (Optional[str]): Override for the fdsnws 'dataselect' service endpoint.
        event_url (Optional[str]): Override for the fdsnws 'event' service endpoint.

    Service overrides are only needed for servers whose FDSN services are not
    at the standard '<base>/fdsnws/<service>/1' paths.
    """
    client: str
    url: str
    is_original: bool
    station_url: Optional[str] = None
    dataselect_url: Optional[str] = None
    event_url: Optional[str] = None

    def service_mappings(self) -> Optional[dict]:
        """Return an obspy-style service_mappings dict, or None if unused."""
        mappings = {
            "station": _normalize_service_url(self.station_url),
            "dataselect": _normalize_service_url(self.dataselect_url),
            "event": _normalize_service_url(self.event_url),
        }
        mappings = {k: v for k, v in mappings.items() if v}
        return mappings or None



class UrlMappings(BaseModel):
    """
    Manages and synchronizes client URL mappings for seismic data retrieval.

    This class maintains a list of known clients, checks for updates, and allows
    users to add new clients. It also provides functionality to load, save, and
    sync mappings with `URL_MAPPINGS`.

    Attributes:
        maps (Optional[dict]): A dictionary mapping client names to URLs.
        df_maps (Optional[Any]): A Pandas DataFrame storing the client mapping data.
        save_path (Path): The file path where client mappings are stored (default: `clients.csv`).

    Methods:
        check_saved_clients(df: pd.DataFrame) -> pd.DataFrame:
            Validates and updates the saved client list by checking against `URL_MAPPINGS`.

        save(extra_clients: List[dict] = None):
            Saves the client mappings to a CSV file and synchronizes them with `URL_MAPPINGS`.

        sync_maps(df_maps: pd.DataFrame):
            Synchronizes the `maps` dictionary with the latest client mappings from a dataframe.

        load():
            Loads the client mappings from the saved file and ensures synchronization.

        get_clients(client_type: ClientType = ClientType.ALL) -> Union[List[str], Dict[str, str]]:
            Retrieves a list of clients based on the specified `client_type`.
    """
    maps: Optional[dict] = {}
    df_maps: Optional[Any] = None
    save_path: Path  = os.path.join(current_directory,"clients.csv")

    def check_saved_clients(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Validates and updates the saved client list by checking against `URL_MAPPINGS`.

        This method ensures that:
        - Clients marked as original but no longer exist in `URL_MAPPINGS` are removed.
        - New clients found in `URL_MAPPINGS` that are not in the saved list are added.

        Args:
            df (pd.DataFrame): The dataframe containing the saved client mappings.

        Returns:
            pd.DataFrame: The updated dataframe with verified client mappings.
        """
        chk_clients = []
        # Check if an original saved client yet exist
        # in the latest URL_MAPPINGS
        for row in df.to_dict('records'):
            
            if row['client'] not in URL_MAPPINGS and row['is_original']:
                continue

            chk_clients.append(row)

        df_chk = pd.DataFrame(chk_clients)
        if df_chk.empty:
            df_chk = pd.DataFrame(columns=['client', 'url', 'is_original'])

        curr_clients = list(df_chk.client)
        # Check if a client exist in URL_MAPPINGS that does not exist
        # in saved clients
        for client, url in URL_MAPPINGS.items():
            if client not in curr_clients:
                df_chk.loc[len(df_chk)] = {
                    'client': client, 
                    'url': url,
                    'is_original': True
                }

        return self._ensure_service_columns(df_chk)

    @staticmethod
    def _ensure_service_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Guarantee the per-service override columns exist (back-compat with
        clients.csv files written before service mappings were supported).
        Columns are forced to object dtype: an all-NaN column read from CSV is
        float64 and would reject string URL assignment."""
        for service in SERVICE_KEYS:
            col = f"{service}_url"
            if col not in df.columns:
                df[col] = None
            df[col] = df[col].astype("object")
        return df


    def save(self, extra_clients: List[dict] = None, merge: bool = False):
        """
        Saves the client mappings to a CSV file and synchronizes them with `URL_MAPPINGS`.

        Args:
            extra_clients (List[dict], optional): Additional client mappings. Each record
                may contain 'client', 'url' and optional 'station_url' / 'dataselect_url' /
                'event_url' service overrides.
            merge (bool): If False (GUI behaviour), saved extra clients not present in
                `extra_clients` are removed — the table is the source of truth. If True
                (config-file behaviour), records are added/updated without deleting
                extra clients configured elsewhere (e.g. via the GUI).
        """
        if os.path.exists(self.save_path):
            df = pd.read_csv(self.save_path)
        else:
            lst_mappings = []
            for k,v in URL_MAPPINGS.items():
                lst_mappings.append({
                    "client": k,
                    "url": v,
                    "is_original": True
                })

            df = pd.DataFrame(lst_mappings)

        df = self.check_saved_clients(df)

        if extra_clients is not None:

            # Remove not present extra clients (skipped in merge mode)
            if not merge:
                saved_extra_clients = [c for c in df.to_dict('records') if not c['is_original']]
                lst_curr_extras = [e['client'] for e in extra_clients]
                for saved_ex in saved_extra_clients:
                    if saved_ex['client'] not in lst_curr_extras:
                        idx = list(df.client).index(saved_ex['client'])
                        df = df.drop(index=idx)
                        df = df.reset_index(drop=True)

                    if saved_ex['client'] in URL_MAPPINGS:
                        del URL_MAPPINGS[saved_ex['client']]


            # Add the additional extra_clients
            for e in extra_clients:
                record = {
                    'client': e['client'],
                    'url': str(e['url']).strip().rstrip('/'),
                    'is_original': False,
                }
                for service in SERVICE_KEYS:
                    record[f"{service}_url"] = _normalize_service_url(e.get(f"{service}_url"))

                try:
                    idx = list(df.client).index(e['client'])
                    for k, v in record.items():
                        if k != 'client':
                            df.loc[idx, k] = v
                except ValueError:
                    df.loc[len(df)] = record


        df.sort_values('client').to_csv(self.save_path, index=False)

        self.sync_maps(df)


    def get_mapping(self, client_name: str) -> Optional[UrlMapping]:
        """
        Return the full UrlMapping record for a client name, or None if the
        client is unknown or has no saved record (plain obspy clients).
        """
        if self.df_maps is None:
            self.load()

        rows = self.df_maps[self.df_maps.client == client_name]
        if rows.empty:
            return None

        row = rows.iloc[0].to_dict()
        return UrlMapping(
            client=row['client'],
            url=row['url'],
            is_original=bool(row['is_original']),
            station_url=_normalize_service_url(row.get('station_url')),
            dataselect_url=_normalize_service_url(row.get('dataselect_url')),
            event_url=_normalize_service_url(row.get('event_url')),
        )


    def create_client(self, client_name: str, user: str = None,
                      password: str = None, user_agent: str = 'SEED-Vault') -> Client:
        """
        Central factory for obspy FDSN clients.

        For clients with per-service endpoint overrides (servers with
        non-standard FDSN paths, see issue #365), the client is constructed
        with base_url + service_mappings; obspy skips endpoint discovery for
        mapped services and discovers the rest from base_url as usual.
        Credentials compose with service mappings.
        """
        kwargs = {'user_agent': user_agent}
        if user:
            kwargs.update(user=user, password=password)

        mapping = self.get_mapping(client_name)
        if mapping is not None and mapping.service_mappings():
            return Client(
                base_url=mapping.url,
                service_mappings=mapping.service_mappings(),
                **kwargs,
            )

        return Client(client_name, **kwargs)

    
    def sync_maps(self, df_maps):
        """
        Synchronizes the `maps` dictionary with the latest client mappings from the dataframe.

        This method updates both the instance's `maps` dictionary and the global `URL_MAPPINGS`
        to reflect the latest client URL assignments.

        Args:
            df_maps (pd.DataFrame): The dataframe containing the client mapping information.
        """
        self.df_maps = df_maps   
        for row in df_maps.to_dict('records'):
            self.maps[row['client']] = row['url']
    
        URL_MAPPINGS.update(self.maps)
        self.maps = URL_MAPPINGS


    def load(self):
        """
        Loads the client mappings from the saved file and ensures synchronization.

        This method:
        - Initializes the `maps` dictionary.
        - Calls `save()` to ensure the client mappings are properly saved and updated.
        """
        self.maps = {}
        self.save()

        # self.df_maps = pd.read_csv(self.save_path)
        # self.sync_maps(self.df_maps)


    def get_extra_records(self) -> List[dict]:
        """
        Full records (including service overrides) for user-added clients,
        used by the settings GUI table and config-file serialization.
        """
        self.load()
        cols = ['client', 'url'] + [f"{s}_url" for s in SERVICE_KEYS]
        return [
            {c: (None if pd.isna(rec.get(c)) else rec.get(c)) for c in cols}
            for rec in self.df_maps.to_dict('records') if not rec['is_original']
        ]


    def get_clients(self, client_type: ClientType = ClientType.ALL):
        """
        Retrieves a list of clients based on the specified `client_type`.

        Args:
            client_type (ClientType, optional): The type of clients to retrieve.
                - `ClientType.ALL`: Returns all clients.
                - `ClientType.ORIGINAL`: Returns only the original clients.
                - `ClientType.EXTRA`: Returns only the extra clients.

        Returns:
            Union[List[str], Dict[str, str]]: A list of client names or a dictionary of client URLs.

        Raises:
            ValueError: If an unknown `client_type` is provided.
        """
        self.load()
        if client_type == ClientType.ALL:
            return list(self.maps.keys())
        
        if client_type == ClientType.ORIGINAL:
            return {c['client']: c['url'] for c in self.df_maps.to_dict('records') if c['is_original']}
        
        if client_type == ClientType.EXTRA:
            return {c['client']: c['url'] for c in self.df_maps.to_dict('records') if not c['is_original']}
        
        raise ValueError(f"Unknown client_type: {client_type}")