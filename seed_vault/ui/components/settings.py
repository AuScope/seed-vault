import streamlit as st
import pandas as pd
from time import sleep

from copy import deepcopy
from seed_vault.enums.common import ClientType
from seed_vault.models.config import AuthConfig, SeismoLoaderSettings
from seed_vault.ui.app_pages.helpers.common import save_filter, reset_config

from seed_vault.service.seismoloader import populate_database_from_sds
from seed_vault.utils.constants import DOC_BASE_URL

import os
import jinja2
from copy import deepcopy


class SettingsComponent:
    settings: SeismoLoaderSettings
    old_settings: SeismoLoaderSettings
    is_new_cred_added = None
    df_clients = None

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings  = settings
        self.old_settings   = deepcopy(settings)

    def add_credential(self):
        for item in self.settings.auths:
            if item.nslc_code == "new":
                return False
        self.settings.auths.append(AuthConfig(nslc_code="XX", username="user", password="password"))
        save_filter(self.settings)
        return True

    def reset_is_new_cred_added(self):
        # sleep(5)
        self.is_new_cred_added = None
        # st.rerun()

    def refresh_filters(self):
        changes = self.settings.has_changed(self.old_settings)
        if changes.get('has_changed', False):
            self.old_settings      = deepcopy(self.settings)
            save_filter(self.settings)
            st.rerun()
    
    def render_auth(self):
        st.write("## Auth Records")
        # auths_lst = [item.model_dump() for item in settings.auths]
        # edited_df = st.data_editor(pd.DataFrame(auths_lst), num_rows="dynamic")

        for index, auth in enumerate(self.settings.auths):
            c1,c2,c3,c4 = st.columns([1,1,1,3])
            # st.write(f"### Credential Set {index + 1}")

            with c1:
                nslc_code = st.text_input(f"Network Code", help="Probably the userauth is per-network so just enter the 2 digit network code. Can also put NN.STA if auth is per-station.", value=auth.nslc_code, key=f"nslc_{index}")
            with c2:
                username = st.text_input(f"Username", value=auth.username, key=f"username_{index}")
            with c3:
                password = st.text_input(f"Password", value=auth.password, type="password", key=f"password_{index}")

            # Update session state with edited values
            self.settings.auths[index] = AuthConfig(nslc_code=nslc_code, username=username, password=password)

            with c4:
                st.text("")
                st.text("")
                if st.button(f"Delete", key=f"remove_{index}"):
                    try:
                        self.settings.auths.pop(index)
                        save_filter(self.settings)
                        self.reset_is_new_cred_added()
                        st.rerun()
                    except Exception as e:
                        st.error(f"An error occured: {str(e)}")

        if st.button("Add Credential Set"):
            try:
                self.reset_is_new_cred_added()
                self.is_new_cred_added = self.add_credential()
                st.rerun()
            except Exception as e:
                st.error(f"An error occured: {str(e)}")

        if self.is_new_cred_added is not None:
            if self.is_new_cred_added:
                st.success("Added a new auth. Please fill up the entries.")
            else:
                st.error("You cannot define duplicate N.S.L.C code.")

            # self.reset_is_new_cred_added()


    def render_db(self):
        try:
            c1, c2 = st.columns([1,1])
            with c1:
                self.settings.db_path = st.text_input("Database Path", value=self.settings.db_path, help="FULL path to your database, e.g. /archive/database.sqlite")
                self.settings.sds_path = st.text_input("Local Seismic Data Archive Path in [SDS structure](https://www.seiscomp.de/seiscomp3/doc/applications/slarchive/SDS.html)",
                                                    value=self.settings.sds_path, help="ROOT path of your archive. If you change this you may have to resync your database.")

            st.write("## Sync database with existing archive")
            c1, c2, c3, c4 = st.columns([1,1,1,2])
            with c1:
                search_patterns = st.text_input("Search Patterns", value="??.*.*.?H?.D.202?.???", help="To input multiple values, separate your entries with comma.").strip().split(",")
            with c4:
                c11, c22 = st.columns([1,1])
                with c11:
                    selected_date_type = st.selectbox("Date selection", ["All", "Custom Time"], index=0)
                with c22:
                    if selected_date_type == "All":
                        newer_than=None
                    else:
                        newer_than = st.date_input("Update Since")
            with c2:
                self.settings.processing.num_processes = int(st.number_input(
                    "Number of Processors", 
                    value=self.settings.processing.num_processes, 
                    min_value=0, 
                    help="Number of Processors >= 0. If set to zero, the app will use all available cpu to perform the operation."
                ))

            with c3:
                self.settings.processing.gap_tolerance = int(st.number_input(
                    "Gap Tolerance (s)", 
                    value=self.settings.processing.gap_tolerance, 
                    min_value=0
                ))


            if st.button("Sync Database", help="Synchronizes your SDS archive given the above parameters."):
                self.reset_is_new_cred_added()
                save_filter(self.settings)
                populate_database_from_sds(
                    sds_path=self.settings.sds_path,
                    db_path=self.settings.db_path,
                    search_patterns=search_patterns,
                    newer_than=newer_than,
                    num_processes=self.settings.processing.num_processes,
                    gap_tolerance=self.settings.processing.gap_tolerance
                )

            self.refresh_filters()
        except Exception as e:
            st.error(str(e))

    def render_clients(self):
        c1, c2 = st.columns([1,1])
        extra_clients = self.settings.client_url_mapping.get_clients(client_type = ClientType.EXTRA) # load_extra_client()
        orig_clients  = self.settings.client_url_mapping.get_clients(client_type = ClientType.ORIGINAL)
        with c1:
            st.write("## Extra Clients")
            df = pd.DataFrame([{"Client Name": k, "Url": v} for k,v in extra_clients.items()])
            if df.empty:
                df = pd.DataFrame(columns=["Client Name", "Url"])
            self.df_clients = st.data_editor(df, hide_index = True, num_rows = "dynamic")            
            # st.write(extra_clients)
        with c2:
            st.write("## Existing Clients (via ObsPy)")
            st.write(orig_clients)

    def reset_config(self):
        self.settings = reset_config()   
        save_filter(self.settings)
        st.success("Settings have been reset to default.")

    def render_license(self):
        st.text(
        """
        CSIRO Open Source Software License Agreement (variation of the BSD/MIT License)

        Copyright (c) 2013, Commonwealth Scientific and Industrial Research Organisation
        (CSIRO) ABN 41 687 119 230.

        All rights reserved. CSIRO is willing to grant you a license to this software
        product on the following terms, except where otherwise indicated for third
        party material.

        Redistribution and use of this software in source and binary forms, with or
        without modification, are permitted provided that the following conditions are
        met:

        1. Redistributions of source code must retain the above copyright notice, this
        list of conditions and the following disclaimer.
        2. Redistributions in binary form must reproduce the above copyright notice,
        this list of conditions and the following disclaimer in the documentation
        and/or other materials provided with the distribution.
        3. Neither the name of CSIRO nor the names of its contributors may be used to
        endorse or promote products derived from this software without specific prior
        written permission of CSIRO.

        EXCEPT AS EXPRESSLY STATED IN THIS LICENCE AND TO THE FULL EXTENT PERMITTED BY
        APPLICABLE LAW, THE SOFTWARE IS PROVIDED "AS-IS". CSIRO AND ITS CONTRIBUTORS
        MAKE NO REPRESENTATIONS, WARRANTIES OR CONDITIONS OF ANY KIND, EXPRESS OR
        IMPLIED, INCLUDING BUT NOT LIMITED TO ANY REPRESENTATIONS, WARRANTIES OR
        CONDITIONS REGARDING THE CONTENTS OR ACCURACY OF THE SOFTWARE, OR OF TITLE,
        MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, NON-INFRINGEMENT, THE ABSENCE
        OF LATENT OR OTHER DEFECTS, OR THE PRESENCE OR ABSENCE OF ERRORS, WHETHER OR NOT
        DISCOVERABLE.

        TO THE FULL EXTENT PERMITTED BY APPLICABLE LAW, IN NO EVENT SHALL CSIRO OR ITS
        CONTRIBUTORS BE LIABLE ON ANY LEGAL THEORY (INCLUDING, WITHOUT LIMITATION, IN AN
        ACTION FOR BREACH OF CONTRACT, NEGLIGENCE OR OTHERWISE) FOR ANY CLAIM, LOSS,
        DAMAGES OR OTHER LIABILITY HOWSOEVER INCURRED. WITHOUT LIMITING THE SCOPE OF THE
        PREVIOUS SENTENCE THE EXCLUSION OF LIABILITY SHALL INCLUDE: LOSS OF PRODUCTION
        OR OPERATION TIME, LOSS, DAMAGE OR CORRUPTION OF DATA OR RECORDS; OR LOSS OF
        ANTICIPATED SAVINGS, OPPORTUNITY, REVENUE, PROFIT OR GOODWILL, OR OTHER ECONOMIC
        LOSS; OR ANY SPECIAL, INCIDENTAL, INDIRECT, CONSEQUENTIAL, PUNITIVE OR EXEMPLARY
        DAMAGES, ARISING OUT OF OR IN CONNECTION WITH THIS LICENCE, THE USE OF THE
        SOFTWARE OR THE USE OF OR OTHER DEALINGS WITH THE SOFTWARE, EVEN IF CSIRO OR ITS
        CONTRIBUTORS HAVE BEEN ADVISED OF THE POSSIBILITY OF SUCH CLAIM, LOSS, DAMAGES
        OR OTHER LIABILITY.

        APPLICABLE LEGISLATION SUCH AS THE AUSTRALIAN CONSUMER LAW MAY IMPLY
        REPRESENTATIONS, WARRANTIES, OR CONDITIONS, OR IMPOSES OBLIGATIONS OR LIABILITY
        ON CSIRO OR ONE OF ITS CONTRIBUTORS IN RESPECT OF THE SOFTWARE THAT CANNOT BE
        WHOLLY OR PARTLY EXCLUDED, RESTRICTED OR MODIFIED "CONSUMER GUARANTEES". IF SUCH
        CONSUMER GUARANTEES APPLY THEN THE LIABILITY OF CSIRO AND ITS CONTRIBUTORS IS
        LIMITED, TO THE FULL EXTENT PERMITTED BY THE APPLICABLE LEGISLATION. WHERE THE
        APPLICABLE LEGISLATION PERMITS THE FOLLOWING REMEDIES TO BE PROVIDED FOR BREACH
        OF THE CONSUMER GUARANTEES THEN, AT ITS OPTION, CSIRO'S LIABILITY IS LIMITED TO
        ANY ONE OR MORE OF THEM:

        1. THE REPLACEMENT OF THE SOFTWARE, THE SUPPLY OF EQUIVALENT SOFTWARE, OR
        SUPPLYING RELEVANT SERVICES AGAIN;
        2. THE REPAIR OF THE SOFTWARE;
        3. THE PAYMENT OF THE COST OF REPLACING THE SOFTWARE, OF ACQUIRING EQUIVALENT
        SOFTWARE, HAVING THE RELEVANT SERVICES SUPPLIED AGAIN, OR HAVING THE SOFTWARE
        REPAIRED.
        """
        )

    def render(self):
        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            st.write("# Settings")
        with c2:
            st.text("")
            st.text("")
            button_col1, button_col2 = st.columns([1, 1])
            with button_col1:
                if st.button("Save Config"):
                    try:
                        self.reset_is_new_cred_added()
                        save_filter(self.settings)
                        df_copy = deepcopy(self.df_clients)
                        df_copy = df_copy.rename(columns={"Client Name": 'client', "Url": 'url'})
                        self.settings.client_url_mapping.save(df_copy.to_dict('records'))
                        with c3:
                            st.text("")
                            st.success("Config is successfully saved.")
                    except Exception as e:
                        with c3:
                            st.text("")
                            st.error(f"An error occured. Make sure there is no null value in the table.")
                            st.error(e)
            with button_col2:
                st.button("Reset Settings", on_click=self.reset_config)

        with c3:
            st.text("")
            st.text("")
            st.link_button("Help", f"{DOC_BASE_URL}/app_settings.html")

        tab1, tab2, tab3, tab4 = st.tabs(["🛠️ Data", "🔑 Credentials", "📡 Clients", "📜 License"])
        with tab1:
            self.render_db()
        with tab2:
            self.render_auth()
        with tab3:
            self.render_clients()
        with tab4:
            self.render_license()
