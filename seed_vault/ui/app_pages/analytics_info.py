"""
Analytics Information Page

This page redirects users to the Analytics tab in the Settings page.
"""

import streamlit as st

st.set_page_config(
    page_title="Analytics Information",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Redirect to Settings page
st.title("📊 Analytics Information")

st.info("""
    **Analytics settings have been moved!**
    
    Please use the **Settings** page and navigate to the **Analytics** tab 
    to view detailed information about analytics and manage your preferences.
""")

st.markdown("---")

# Provide navigation button
if st.button("⚙️ Go to Settings", type="primary", use_container_width=False):
    st.switch_page("app_pages/settings.py")
