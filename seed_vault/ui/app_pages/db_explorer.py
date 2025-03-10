import streamlit as st
import pandas as pd
import time

st.set_page_config(
    page_title="Data Explorer",
    page_icon="🛢️",
    layout="wide",
    initial_sidebar_state="expanded",
)

from seed_vault.ui.app_pages.helpers.common import get_app_settings
from seed_vault.ui.components.data_explorer import DataExplorerComponent

settings = get_app_settings()


if "data_explorer_page" not in st.session_state:
    data_explorer_page                  = DataExplorerComponent(settings)
    st.session_state.data_explorer_page = data_explorer_page
else:
    data_explorer_page                  = st.session_state.data_explorer_page
    

data_explorer_page.render()