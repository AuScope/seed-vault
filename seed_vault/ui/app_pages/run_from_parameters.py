import streamlit as st
from seed_vault.ui.app_pages.helpers.common import get_direct_settings
import os
import jinja2
import pickle

st.set_page_config(
    page_title="Run from Parameters",
    # page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.info(
    """
In this page, you can directly set the search configs for your data and run the flow without needing
to go through the steps of main flow. Suits use cases where you are quite familiar with the config parameter
settings and when you do not want of much fine tuning on selection of Events and Stations.
"""
)

from seed_vault.ui.app_pages.helpers.common import get_app_settings
from seed_vault.ui.components.run_from_config import RunFromConfigComponent

settings = get_direct_settings()


if "run_from_config_page" not in st.session_state:
    run_from_config_page           = RunFromConfigComponent(settings)
    st.session_state.run_from_config_page = run_from_config_page
else:
    run_from_config_page           = st.session_state.run_from_config_page
    

run_from_config_page.render()
