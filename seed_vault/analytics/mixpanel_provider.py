"""
Mixpanel provider for Seed Vault Analytics.

Implements Mixpanel Analytics SDK with event tracking and user properties.
"""

import os
from typing import Optional, Dict, Any

try:
    from mixpanel import Mixpanel
    MIXPANEL_AVAILABLE = True
except ImportError:
    MIXPANEL_AVAILABLE = False

from .base_telemetry import BaseTelemetryProvider, MixpanelConfig


class MixpanelTelemetryProvider(BaseTelemetryProvider):
    """
    Mixpanel telemetry provider.
    
    Features:
    - Mixpanel Analytics SDK integration
    - Page view tracking as custom events
    - Custom event tracking with properties
    - User profile properties
    - Graceful fallback if SDK not installed
    
    Example:
        >>> from seed_vault.analytics import MixpanelTelemetryProvider, MixpanelConfig, TelemetryContext
        >>> 
        >>> config = MixpanelConfig(
        ...     enabled=True,
        ...     project_token="your-mixpanel-token"
        ... )
        >>> context = TelemetryContext(db_path="SVdata/database.sqlite")
        >>> 
        >>> provider = MixpanelTelemetryProvider(
        ...     config=config,
        ...     db_path=context.db_path,
        ...     client_id=context.client_id,
        ...     session_id=context.session_id,
        ...     runtime=context.runtime
        ... )
        >>> 
        >>> provider.track_page_view("/event-search", "Event Search")
        >>> provider.track_event("workflow_started", {"workflow_type": "event_based"})
    """
    
    def __init__(
        self,
        config: MixpanelConfig,
        db_path: str,
        client_id: str,
        session_id: str,
        runtime: str
    ):
        """
        Initialize Mixpanel provider.
        
        Args:
            config: MixpanelConfig instance with project_token
            db_path: Path to SQLite database
            client_id: Persistent UUID for user tracking
            session_id: Session-specific UUID
            runtime: Runtime environment ("streamlit" or "cli")
        """
        super().__init__(config, db_path, client_id, session_id, runtime)
        self.config: MixpanelConfig = config  # Type hint for IDE support
        self._mixpanel_client: Optional[Mixpanel] = None
        
        if not MIXPANEL_AVAILABLE:
            if os.getenv("DEBUG_TELEMETRY"):
                print("[Mixpanel] SDK not installed. Install with: poetry add mixpanel")
            return
        
        if self.is_enabled:
            self._init_mixpanel()
    
    def _init_mixpanel(self) -> None:
        """Initialize the Mixpanel SDK client."""
        try:
            self._mixpanel_client = Mixpanel(self.config.project_token)
            
            # Set user profile properties
            self._mixpanel_client.people_set(self._client_id, {
                'runtime': self._runtime,
                'lib_version': self.LIBRARY_VERSION,
                '$name': f'User {self._client_id[:8]}'  # Shortened for privacy
            })
            
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Mixpanel] Initialized with client_id: {self._client_id}")
                
        except Exception as e:
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Mixpanel] Failed to initialize: {e}")
            self._mixpanel_client = None
    
    def track_page_view(self, page_path: str, page_title: str) -> None:
        """
        Track a page view as a custom event.
        
        Mixpanel doesn't have a built-in page_view event, so we track it
        as a custom "Page Viewed" event with path and title properties.
        
        Args:
            page_path: Virtual page path (e.g., "/event-search")
            page_title: Human-readable page title (e.g., "Event Search")
        """
        if not self.is_enabled or not self._mixpanel_client:
            return
        
        self.track_event("Page Viewed", {
            "page_path": page_path,
            "page_title": page_title,
        })
    
    def track_event(self, event_name: str, params: Optional[Dict[str, Any]] = None) -> None:
        """
        Track a custom event to Mixpanel.
        
        Args:
            event_name: Name of the event (e.g., "workflow_started")
            params: Optional dictionary of event properties
        """
        if not self.is_enabled or not self._mixpanel_client:
            return
        
        # Enrich parameters with common metadata
        enriched_params = self.enrich_params(params)
        
        # Send to Mixpanel
        self._send_to_provider({
            'event_name': event_name,
            'properties': enriched_params
        })
    
    def _send_to_provider(self, payload: Dict[str, Any]) -> None:
        """
        Send event to Mixpanel.
        
        Args:
            payload: Dictionary with 'event_name' and 'properties'
        """
        try:
            event_name = payload['event_name']
            properties = payload['properties']
            
            # Add distinct_id (required by Mixpanel)
            properties['distinct_id'] = self._client_id
            
            self._mixpanel_client.track(
                self._client_id,
                event_name,
                properties
            )
            
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Mixpanel] Event sent: {event_name}")
                
        except Exception as e:
            # Fail silently - telemetry should never break the app
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Mixpanel] Failed to send event: {e}")
    
    @property
    def is_enabled(self) -> bool:
        """Check if Mixpanel provider is enabled and SDK is available."""
        return MIXPANEL_AVAILABLE and super().is_enabled
