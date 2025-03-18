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
Here you can directly set the search configs and run your desired workflow instantly.
"""
)

from seed_vault.ui.app_pages.helpers.common import get_app_settings
from seed_vault.ui.components.run_from_config import RunFromConfigComponent

current_page = st.session_state.get("current_page", None)
new_page = "run_config"
if current_page != new_page:
    st.session_state.clear()
st.session_state["current_page"] = new_page


settings = get_direct_settings()

if "run_from_config_page" not in st.session_state:
    run_from_config_page           = RunFromConfigComponent(settings)
    st.session_state.run_from_config_page = run_from_config_page
else:
    run_from_config_page           = st.session_state.run_from_config_page
    

run_from_config_page.render()
