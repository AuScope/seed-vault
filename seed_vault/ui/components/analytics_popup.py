"""
Analytics Consent Popup Component

This module provides a Streamlit component that displays an analytics consent popup
when the user first loads the application and analytics is enabled.
"""

import streamlit as st
from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.ui.app_pages.helpers.common import save_filter, set_app_settings


class AnalyticsPopup:
    """
    A Streamlit component that displays an analytics consent notification.
    
    The popup appears when:
    - analytics_enabled == True
    - analytics_popup_dismissed == False
    
    It provides options to:
    - Learn more about analytics (navigates to dedicated page)
    - Disable analytics
    - Dismiss the popup
    """
    
    def __init__(self, settings: SeismoLoaderSettings):
        """
        Initialize the AnalyticsPopup component.
        
        Args:
            settings (SeismoLoaderSettings): The current application settings
        """
        self.settings = settings
    
    def should_show(self) -> bool:
        """
        Determine if the popup should be displayed.
        
        Returns:
            bool: True if popup should be shown, False otherwise
        """
        return (
            self.settings.analytics_enabled and 
            not self.settings.analytics_popup_dismissed
        )
    
    def render(self) -> None:
        """
        Render the analytics consent popup.
        
        This method displays the popup with action buttons and handles
        user interactions to update settings accordingly.
        """
        if not self.should_show():
            return
        
        # Create a container for the popup at the top of the page
        with st.container():
            # Use columns for layout
            col1, col2 = st.columns([4, 1])
            
            with col1:
                st.info(
                    "📊 **Analytics Notice:** We collect anonymous usage analytics to improve Seed Vault. "
                    "You can disable analytics at any time in Settings.",
                    icon="ℹ️"
                )
            
            with col2:
                # Create a container for buttons stacked vertically
                if st.button("✖ Dismiss", key="analytics_dismiss", use_container_width=True):
                    self._dismiss_popup()
                    st.rerun()
            
            # Action buttons below the notice
            col_learn, col_disable, col_space = st.columns([1, 1, 2])
            
            with col_learn:
                if st.button("📖 Learn More", key="analytics_learn", use_container_width=True):
                    self._navigate_to_analytics_page()
            
            with col_disable:
                if st.button("🚫 Disable Analytics", key="analytics_disable", use_container_width=True):
                    self._disable_analytics()
                    st.rerun()
            
            st.markdown("---")
    
    def _dismiss_popup(self) -> None:
        """
        Mark the popup as dismissed without disabling analytics.
        
        This updates the settings and persists the change to disk.
        """
        self.settings.analytics_popup_dismissed = True
        set_app_settings(self.settings)
        save_filter(self.settings)
        
        # Also update session state to ensure it persists
        if 'analytics_popup_dismissed' not in st.session_state:
            st.session_state.analytics_popup_dismissed = True
    
    def _disable_analytics(self) -> None:
        """
        Disable analytics collection and dismiss the popup.
        
        This updates the settings and persists the change to disk.
        """
        self.settings.analytics_enabled = False
        self.settings.analytics_popup_dismissed = True
        set_app_settings(self.settings)
        save_filter(self.settings)
        
        # Update session state
        if 'analytics_enabled' not in st.session_state:
            st.session_state.analytics_enabled = False
        if 'analytics_popup_dismissed' not in st.session_state:
            st.session_state.analytics_popup_dismissed = True
        
        st.success("✅ Analytics disabled successfully!")
    
    def _navigate_to_analytics_page(self) -> None:
        """
        Navigate to the Settings page with Analytics tab pre-selected.
        
        This uses Streamlit's navigation and session state to switch to the settings page
        and open the Analytics tab.
        """
        # Dismiss popup when user wants to learn more
        self.settings.analytics_popup_dismissed = True
        set_app_settings(self.settings)
        save_filter(self.settings)
        
        # Set session state to open Analytics tab
        st.session_state['open_analytics_tab'] = True
        
        # Navigate to settings page using st.switch_page
        st.switch_page("app_pages/settings.py")
