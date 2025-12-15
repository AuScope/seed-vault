"""
Telemetry helper functions for Streamlit app integration.

Provides a singleton telemetry manager for consistent tracking across the app.
"""

import streamlit as st
from typing import Optional
from seed_vault.analytics import TelemetryManager
from seed_vault.models.config import SeismoLoaderSettings


_telemetry_manager: Optional[TelemetryManager] = None


def init_telemetry_client(settings: SeismoLoaderSettings, db_path: str) -> TelemetryManager:
    """
    Initialize or get the telemetry manager singleton.
    
    This ensures we only create one telemetry manager per session,
    avoiding multiple client_id generations. Supports multiple analytics
    providers (GA4, Amplitude, etc.) simultaneously.
    
    Args:
        settings: SeismoLoaderSettings instance
        db_path: Path to SQLite database
    
    Returns:
        TelemetryManager instance
    """
    global _telemetry_manager
    
    # Check if we already have a manager in session state
    if 'telemetry_client' not in st.session_state:
        _telemetry_manager = TelemetryManager.from_settings(settings, db_path=db_path)
        st.session_state.telemetry_client = _telemetry_manager
    else:
        _telemetry_manager = st.session_state.telemetry_client
    
    return _telemetry_manager


def get_telemetry_client() -> Optional[TelemetryManager]:
    """
    Get the current telemetry manager from session state.
    
    Returns:
        TelemetryManager if initialized, None otherwise
    """
    return st.session_state.get('telemetry_client', None)


def track_page_view(page_path: str, page_title: str) -> None:
    """
    Track a page view using the session telemetry client.
    
    Only sends the page view once per unique page to avoid duplicate
    tracking on Streamlit reruns. Tracks again if the user navigates
    to a different page and then returns.
    
    Args:
        page_path: Virtual page path (e.g., "/event-search")
        page_title: Page title (e.g., "Event Search")
    """
    # Track the current page to detect actual navigation changes
    last_tracked_page = st.session_state.get('_last_tracked_page', None)
    
    # Only track if we've navigated to a different page
    # This prevents duplicate tracking on reruns while allowing
    # re-tracking when user navigates away and back
    if last_tracked_page != page_path:
        telemetry = get_telemetry_client()
        if telemetry:
            telemetry.track_page_view(page_path, page_title)
            st.session_state._last_tracked_page = page_path


def track_event(event_name: str, params: Optional[dict] = None) -> None:
    """
    Track a custom event using the session telemetry client.
    
    Args:
        event_name: Name of the event
        params: Optional event parameters
    """
    telemetry = get_telemetry_client()
    if telemetry:
        telemetry.track_event(event_name, params or {})
