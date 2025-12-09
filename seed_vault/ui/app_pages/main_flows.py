import streamlit as st

st.set_page_config(
    page_title="Seed Vault",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        details summary p {
            font-size: 20px !important;
            font-weight: bold !important;
        }
        section[data-testid="stSidebar"] {
            width: 450px !important;
        }
        section[data-testid="stMain"] {
            width: 100% !important;
            padding: 0;
        }
        iframe[data-testid="stCustomComponentV1"] {
            height: 500px !important;
        }
        # div[data-testid="stHorizontalBlock"] {
        #     display: flex;
        #     align-items: end;
        # }
        .vertical-align-bottom {
            display: flex;
            align-items: flex-end !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


from seed_vault.ui.components.workflows_combined import CombinedBasedWorkflow
from seed_vault.ui.components.analytics_popup import AnalyticsPopup
from seed_vault.ui.app_pages.helpers.common import get_app_settings
from seed_vault.ui.app_pages.helpers.telemetry import track_page_view

current_page = st.session_state.get("current_page", None)
new_page = "main_flow"

if current_page != new_page:
    st.session_state.clear()

st.session_state["current_page"] = new_page

# Display analytics popup if conditions are met
settings = get_app_settings(create_new=False, empty_geo=False)
analytics_popup = AnalyticsPopup(settings)
analytics_popup.render()

# Track page view
track_page_view("/main-flows", "Main Flows")

if "combined_based_workflow" not in st.session_state:
    combined_based_workflow                  = CombinedBasedWorkflow()
    st.session_state.combined_based_workflow = combined_based_workflow
else:
    combined_based_workflow                  = st.session_state.combined_based_workflow
    
combined_based_workflow.render()



