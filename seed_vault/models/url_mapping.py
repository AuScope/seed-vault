import os

from pathlib import Path

from pydantic import BaseModel, Field
from typing import List, Optional, Any
from obspy.clients.fdsn.header import URL_MAPPINGS
import pandas as pd

from seed_vault.enums.common import ClientType


current_directory = os.path.dirname(os.path.abspath(__file__))

CLIENTS_CSV_PATH = os.path.join(current_directory, "clients.csv")

# Optional per-service URL columns in clients.csv (see seed_vault.service.fdsn_client).
SERVICE_COLUMNS = ["dataselect", "event", "station"]
CSV_COLUMNS = ["client", "url", "is_original"] + SERVICE_COLUMNS


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add missing service columns (older clients.csv files) and blank out NaNs."""
    for col in SERVICE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df[SERVICE_COLUMNS] = df[SERVICE_COLUMNS].fillna("").astype(str)
    df["url"] = df["url"].fillna("").astype(str)
    return df

class UrlMapping(BaseModel):
    """
    Represents a mapping between a seismic data client and its corresponding URL.

    Attributes:
        client (str): The name of the seismic data client.
        url (str): The associated URL for retrieving seismic data.
        is_original (bool): Indicates whether the client is an original one from `URL_MAPPINGS`.
    """
    client: str
    url: str
    is_original: bool



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
    # Resolved at construction time so the location can be overridden (e.g. in tests).
    save_path: Path  = Field(default_factory=lambda: CLIENTS_CSV_PATH)

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
            # ObsPy's composite pseudo-clients (e.g. "EARTHSCOPE+USGS") route different
            # services to different servers; list the real servers individually instead.
            if row['is_original'] and '+' in str(row['client']):
                continue

            chk_clients.append(row)

        df_chk = pd.DataFrame(chk_clients)

        curr_clients = list(df_chk.client)
        # Check if a client exist in URL_MAPPINGS that does not exist
        # in saved clients
        for client, url in URL_MAPPINGS.items():
            if client not in curr_clients and '+' not in client:
                df_chk.loc[len(df_chk)] = {
                    'client': client, 
                    'url': url,
                    'is_original': True
                }

        return df_chk


    def save(self, extra_clients: List[dict] = None):
        """
        Saves the client mappings to a CSV file and synchronizes them with `URL_MAPPINGS`.

        This method:
        - Loads the existing client mappings if a saved file exists.
        - Updates the list with newly added `extra_clients` if provided.
        - Removes outdated extra clients that are no longer in use.
        - Writes the updated mappings back to disk.
        - Synchronizes the mappings with `URL_MAPPINGS`.

        Args:
            extra_clients (List[dict], optional): A list of additional client mappings to add.
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

        df = _normalise_columns(df)
        df = self.check_saved_clients(df)
        df = _normalise_columns(df)

        if extra_clients is not None:

            # Remove not present extra clients
            saved_extra_clients = [c for c in df.to_dict('records') if not c['is_original']]
            lst_curr_extras = [e['client'] for e in extra_clients]
            for saved_ex in saved_extra_clients:
                if saved_ex['client'] not in lst_curr_extras:
                    idx = list(df.client).index(saved_ex['client'])
                    df = df.drop(index=idx)
                    df = df.reset_index(drop=True)

                if saved_ex['client'] in URL_MAPPINGS:
                    del URL_MAPPINGS[saved_ex['client']]


            # Add the additional extra_clients (with optional per-service URLs)
            for e in extra_clients:
                # Only overwrite service columns that were supplied, so callers that
                # just pass {client, url} (e.g. the legacy web UI) keep existing mappings.
                services = {col: (e.get(col) or "") for col in SERVICE_COLUMNS if col in e}
                if e['client'] in list(df.client):
                    idx = list(df.client).index(e['client'])
                    df.loc[idx, 'url'] = e.get('url') or ""
                    for col, val in services.items():
                        df.loc[idx, col] = val
                else:
                    df.loc[len(df)] = {
                        'client': e['client'],
                        'url': e.get('url') or "",
                        'is_original': False,
                        **{col: services.get(col, "") for col in SERVICE_COLUMNS},
                    }


        df[CSV_COLUMNS].sort_values('client').to_csv(self.save_path, index=False)

        self.sync_maps(df)

    
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
            url = row['url']
            if not url:
                url = next((row[c] for c in SERVICE_COLUMNS if row.get(c) and row[c].lower() != "none"), "")
            self.maps[row['client']] = url
    
        URL_MAPPINGS.update(self.maps)
        # Expose ObsPy's mappings minus its composite pseudo-clients ("A+B"), unless the
        # user deliberately saved one under that name.
        known = set(df_maps.client)
        self.maps = {k: v for k, v in URL_MAPPINGS.items() if k in known or '+' not in k}


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

    def get_extra_client_details(self) -> List[dict]:
        """User-added clients as dicts: client, url, dataselect, event, station."""
        self.load()
        return [{k: ("" if c.get(k) is None else str(c.get(k))) for k in ["client", "url"] + SERVICE_COLUMNS}
                for c in self.df_maps.to_dict('records') if not c['is_original']]