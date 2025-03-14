import streamlit as st
import pandas as pd
import time

st.set_page_config(
    page_title="Settings",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

from seed_vault.ui.app_pages.helpers.common import get_app_settings
from seed_vault.ui.components.settings import SettingsComponent

current_page = st.session_state.get("current_page", None)
new_page = "settings"
if current_page != new_page:
    st.session_state.clear()
st.session_state["current_page"] = new_page

settings = get_app_settings()


if "settings_page" not in st.session_state:
    settings_page                  = SettingsComponent(settings)
    st.session_state.settings_page = settings_page
else:
    settings_page                  = st.session_state.settings_page
    

settings_page.render()