"""
Telemetry Client for Seed Vault Analytics.

Tracks events and page views to Google Analytics 4 with SQLite-persistent client IDs.
"""

import os
import sys
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Optional, Dict, Any
from pathlib import Path
import requests
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()


@dataclass
class TelemetryConfig:
    """Configuration for telemetry client."""
    measurement_id: Optional[str]
    api_secret: Optional[str]
    analytics_enabled: bool
    db_path: str
    
    @property
    def is_valid(self) -> bool:
        """Check if telemetry configuration is valid and enabled."""
        return (
            self.analytics_enabled and
            self.measurement_id is not None and
            self.api_secret is not None and
            len(self.measurement_id) > 0 and
            len(self.api_secret) > 0
        )


class TelemetryClient:
    """
    Client for tracking analytics events and page views.
    
    Features:
    - SQLite-persistent client_id for consistent user tracking
    - Session-based session_id (per process)
    - GA4 integration with virtual page paths
    - Graceful failure when disabled or misconfigured
    - Runtime detection (Streamlit vs CLI)
    
    Example:
        >>> from seed_vault.analytics import TelemetryClient
        >>> from seed_vault.models.config import SeismoLoaderSettings
        >>> 
        >>> settings = SeismoLoaderSettings.from_cfg_file("config.cfg")
        >>> telemetry = TelemetryClient(settings, db_path="SVdata/database.sqlite")
        >>> 
        >>> # Track a virtual page view
        >>> telemetry.track_page_view("/event-search", "Event Search")
        >>> 
        >>> # Track a custom event
        >>> telemetry.track_event("flow_started", {"flow_type": "event_based"})
    """
    
    GA_ENDPOINT = "https://www.google-analytics.com/mp/collect"
    REQUEST_TIMEOUT = 2  # seconds
    LIBRARY_VERSION = "1.0.0"  # TODO: Extract from package metadata
    
    def __init__(self, settings, db_path: str):
        """
        Initialize the telemetry client.
        
        Args:
            settings: SeismoLoaderSettings instance with analytics_enabled flag
            db_path: Path to SQLite database for storing persistent client_id
        """
        self.config = TelemetryConfig(
            measurement_id=os.getenv("GA_MEASUREMENT_ID"),
            api_secret=os.getenv("GA_API_SECRET"),
            analytics_enabled=getattr(settings, 'analytics_enabled', False),
            db_path=db_path
        )
        
        self._client_id: Optional[str] = None
        self._session_id: str = str(uuid.uuid4())
        self._runtime: str = self._detect_runtime()
        
        # Initialize database and load/create client_id
        if self.config.is_valid:
            self._init_database()
            self._client_id = self._get_or_create_client_id()
    
    def _detect_runtime(self) -> str:
        """
        Detect whether running under Streamlit or CLI.
        
        Returns:
            "streamlit" if running under Streamlit, "cli" otherwise
        """
        # Check if streamlit is in the modules
        if 'streamlit' in sys.modules:
            # Additional check for streamlit runtime
            try:
                import streamlit as st
                # If we can access streamlit session state, we're in streamlit
                _ = st.session_state
                return "streamlit"
            except:
                pass
        
        # Check command line for streamlit
        if any('streamlit' in arg.lower() for arg in sys.argv):
            return "streamlit"
        
        return "cli"
    
    def _init_database(self) -> None:
        """
        Initialize the analytics_metadata table in SQLite.
        
        Creates the table if it doesn't exist.
        """
        try:
            # Ensure parent directory exists
            db_dir = Path(self.config.db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            
            with sqlite3.connect(self.config.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS analytics_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
                conn.commit()
        except Exception as e:
            # Silently fail - telemetry should not break the app
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Telemetry] Failed to initialize database: {e}")
    
    def _get_or_create_client_id(self) -> str:
        """
        Get persistent client_id from database or create a new one.
        
        Returns:
            UUID string representing the client ID
        """
        try:
            with sqlite3.connect(self.config.db_path) as conn:
                cursor = conn.execute(
                    "SELECT value FROM analytics_metadata WHERE key = 'client_id'"
                )
                row = cursor.fetchone()
                
                if row:
                    return row[0]
                
                # Generate new client_id
                new_client_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO analytics_metadata (key, value) VALUES ('client_id', ?)",
                    (new_client_id,)
                )
                conn.commit()
                
                if os.getenv("DEBUG_TELEMETRY"):
                    print(f"[Telemetry] Created new client_id: {new_client_id}")
                
                return new_client_id
                
        except Exception as e:
            # Fallback to session-only client_id
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Telemetry] Failed to get/create client_id: {e}")
            return str(uuid.uuid4())
    
    def track_page_view(self, page_path: str, page_title: str) -> None:
        """
        Track a page view with a virtual path.
        
        This creates a real GA4 page_view event with a virtual URL based on the page_path.
        The app renders multiple logical screens on the same physical URL, so we use
        virtual paths to differentiate them in analytics.
        
        Args:
            page_path: Virtual page path (e.g., "/event-search", "/station-search")
            page_title: Human-readable page title (e.g., "Event Search")
        
        Example:
            >>> telemetry.track_page_view("/event-search", "Event Search")
            >>> telemetry.track_page_view("/waveform-download", "Waveform Download")
        """
        if not self.config.is_valid:
            return
        
        # Construct virtual URL
        # In production, you might want to use the actual base URL from config
        base_url = os.getenv("APP_BASE_URL", "http://localhost:8501")
        full_url = f"{base_url}{page_path}"
        
        self.track_event("page_view", {
            "page_location": full_url,
            "page_title": page_title,
            "page_path": page_path,
        })
    
    def track_event(self, event_name: str, params: Optional[Dict[str, Any]] = None) -> None:
        """
        Track a custom event to Google Analytics 4.
        
        Args:
            event_name: Name of the event (e.g., "flow_started", "download_complete")
            params: Optional dictionary of event parameters
        
        Example:
            >>> telemetry.track_event("flow_started", {"flow_type": "event_based"})
            >>> telemetry.track_event("download_complete", {
            ...     "data_type": "waveform",
            ...     "num_stations": 5,
            ...     "duration_seconds": 120
            ... })
        """
        if not self.config.is_valid:
            return
        
        if params is None:
            params = {}
        
        # Inject standard parameters
        enriched_params = {
            **params,
            "session_id": self._session_id,
            "runtime": self._runtime,
            "lib_version": self.LIBRARY_VERSION,
        }
        
        # Build GA4 measurement protocol payload
        payload = {
            "client_id": self._client_id,
            "events": [
                {
                    "name": event_name,
                    "params": enriched_params
                }
            ]
        }
        
        # Send to GA4
        self._post_to_ga(payload)
    
    def _post_to_ga(self, payload: Dict[str, Any]) -> None:
        """
        POST event payload to Google Analytics 4 Measurement Protocol.
        
        Args:
            payload: GA4 measurement protocol payload
        """
        try:
            url = f"{self.GA_ENDPOINT}?measurement_id={self.config.measurement_id}&api_secret={self.config.api_secret}"
            
            response = requests.post(
                url,
                json=payload,
                timeout=self.REQUEST_TIMEOUT,
                headers={"Content-Type": "application/json"}
            )
            
            # GA4 Measurement Protocol returns 204 on success
            if response.status_code not in (200, 204):
                if os.getenv("DEBUG_TELEMETRY"):
                    print(f"[Telemetry] GA4 returned status {response.status_code}")
            
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Telemetry] Event sent: {payload['events'][0]['name']}")
                
        except requests.exceptions.Timeout:
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Telemetry] Request timeout")
        except Exception as e:
            # Fail silently - telemetry should never break the app
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Telemetry] Failed to send event: {e}")
    
    @property
    def is_enabled(self) -> bool:
        """Check if telemetry is enabled and properly configured."""
        return self.config.is_valid
    
    def get_client_id(self) -> Optional[str]:
        """Get the current client ID (for debugging purposes)."""
        return self._client_id
    
    def get_session_id(self) -> str:
        """Get the current session ID."""
        return self._session_id


def init_telemetry(settings, db_path: str) -> TelemetryClient:
    """
    Helper function to initialize telemetry client.
    
    Args:
        settings: SeismoLoaderSettings instance
        db_path: Path to SQLite database
    
    Returns:
        Initialized TelemetryClient instance
    
    Example:
        >>> from seed_vault.analytics import init_telemetry
        >>> from seed_vault.models.config import SeismoLoaderSettings
        >>> 
        >>> settings = SeismoLoaderSettings.from_cfg_file("config.cfg")
        >>> telemetry = init_telemetry(settings, "SVdata/database.sqlite")
    """
    return TelemetryClient(settings, db_path)
