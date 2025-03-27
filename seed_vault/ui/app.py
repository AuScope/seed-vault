import streamlit as st

pg = st.navigation([
    st.Page("app_pages/main_flows.py", icon="🌎"), 
    st.Page("app_pages/run_from_parameters.py", icon="🚀"),
    st.Page("app_pages/db_explorer.py", icon="🛢️"),
    st.Page("app_pages/settings.py", icon="⚙️"),
    # st.Page("app_pages/license.py", icon="📜"),
    ]
)

pg.run()