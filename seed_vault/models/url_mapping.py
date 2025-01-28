import os
import json

from pathlib import Path

from pydantic import BaseModel
from typing import List, Optional, Any
from obspy.clients.fdsn.header import URL_MAPPINGS
import pandas as pd

from seed_vault.enums.common import ClientType


current_directory = os.path.dirname(os.path.abspath(__file__))

class UrlMapping(BaseModel):
    client: str
    url: str
    is_original: bool



class UrlMappings(BaseModel):
    maps: Optional[dict] = {}
    df_maps: Optional[Any] = None
    save_path: Path  = os.path.join(current_directory,"clients.csv")

    def check_saved_clients(self, df: pd.DataFrame) -> pd.DataFrame:
        chk_clients = []
        # Check if an original saved client yet exist
        # in the latest URL_MAPPINGS
        for row in df.to_dict('records'):
            
            if row['client'] not in URL_MAPPINGS and row['is_original']:
                continue

            chk_clients.append(row)

        df_chk = pd.DataFrame(chk_clients)

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

        return df_chk


    def save(self, extra_clients: List[dict] = None):
        
        # df = pd.DataFrame(columns=["client", "url", "is_original"])
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


            # Add inputted extra clients                
            for e in extra_clients:
                try:
                    idx = list(df.client).index(e['client'])
                    df.loc[idx, 'url'] = e['url']
                except Exception as err: 
                    df.loc[len(df)] = {
                        'client': e['client'], 
                        'url': e['url'],
                        'is_original': False
                    }
            

        df.sort_values('client').to_csv(self.save_path, index=False)

        self.sync_maps(df)

        # return df
    
    def sync_maps(self, df_maps):
        self.df_maps = df_maps   
        for row in df_maps.to_dict('records'):
            self.maps[row['client']] = row['url']
    
        URL_MAPPINGS.update(self.maps)
        self.maps = URL_MAPPINGS


    def load(self):
        self.maps = {}

        self.save()

        # self.df_maps = pd.read_csv(self.save_path)

        # self.sync_maps(self.df_maps)
        

    def get_clients(self, client_type: ClientType = ClientType.ALL):
        self.load()
        if client_type == ClientType.ALL:
            return list(self.maps.keys())
        
        if client_type == ClientType.ORIGINAL:
            return {c['client']: c['url'] for c in self.df_maps.to_dict('records') if c['is_original']}
        
        if client_type == ClientType.EXTRA:
            return {c['client']: c['url'] for c in self.df_maps.to_dict('records') if not c['is_original']}
        
        raise ValueError(f"Unknown client_type: {client_type}")