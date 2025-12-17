"""
RudderStack provider for Seed Vault Analytics.

Implements RudderStack SDK with event tracking. RudderStack acts as a
Customer Data Platform (CDP) that routes events to multiple destinations
(GA4, Amplitude, Mixpanel, etc.) from a single integration point.
"""

import os
from typing import Optional, Dict, Any

try:
    import rudderstack.analytics as rudder
    RUDDERSTACK_AVAILABLE = True
except ImportError:
    RUDDERSTACK_AVAILABLE = False

from .base_telemetry import BaseTelemetryProvider, RudderStackConfig


class RudderStackTelemetryProvider(BaseTelemetryProvider):
    """
    RudderStack telemetry provider.
    
    Features:
    - RudderStack Python SDK integration
    - Routes events to multiple downstream destinations
    - Page view tracking via page() method
    - Custom event tracking via track() method
    - User identification via identify() method
    - Graceful fallback if SDK not installed
    
    Example:
        >>> from seed_vault.analytics import RudderStackTelemetryProvider, RudderStackConfig, TelemetryContext
        >>> 
        >>> config = RudderStackConfig(
        ...     enabled=True,
        ...     write_key="your-write-key",
        ...     dataPlaneUrl="https://your-data-plane.com"
        ... )
        >>> context = TelemetryContext(db_path="SVdata/database.sqlite")
        >>> 
        >>> provider = RudderStackTelemetryProvider(
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
        config: RudderStackConfig,
        db_path: str,
        client_id: str,
        session_id: str,
        runtime: str
    ):
        """
        Initialize RudderStack provider.
        
        Args:
            config: RudderStackConfig instance with write_key and dataPlaneUrl
            db_path: Path to SQLite database
            client_id: Persistent UUID for user tracking
            session_id: Session-specific UUID
            runtime: Runtime environment ("streamlit" or "cli")
        """
        super().__init__(config, db_path, client_id, session_id, runtime)
        self.config: RudderStackConfig = config  # Type hint for IDE support
        self._initialized = False
        
        if not RUDDERSTACK_AVAILABLE:
            if os.getenv("DEBUG_TELEMETRY"):
                print("[RudderStack] SDK not installed. Install with: poetry add rudder-sdk-python")
            return
        
        if self.is_enabled:
            self._init_rudderstack()
    
    def _init_rudderstack(self) -> None:
        """Initialize the RudderStack SDK client."""
        try:
            # Configure RudderStack - use the data plane URL exactly as provided
            rudder.write_key = self.config.write_key
            rudder.dataPlaneUrl = self.config.dataPlaneUrl
            
            # Set debug mode if requested
            if os.getenv("DEBUG_TELEMETRY"):
                rudder.debug = True
            
            # Identify the user with context properties
            rudder.identify(
                user_id=self._client_id,
                traits={
                    'runtime': self._runtime,
                    'lib_version': self.LIBRARY_VERSION,
                }
            )
            
            self._initialized = True
            
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[RudderStack] Initialized with client_id: {self._client_id}")
                print(f"[RudderStack] Data plane URL: {self.config.dataPlaneUrl}")
                
        except Exception as e:
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[RudderStack] Failed to initialize: {e}")
            self._initialized = False
    
    def track_page_view(self, page_path: str, page_title: str) -> None:
        """
        Track a page view using RudderStack's page() method.
        
        RudderStack has a dedicated page() method for page tracking,
        which is automatically routed to all configured destinations.
        
        Args:
            page_path: Virtual page path (e.g., "/event-search")
            page_title: Human-readable page title (e.g., "Event Search")
        """
        if not self.is_enabled or not self._initialized:
            return
        
        try:
            # Build properties with enriched metadata
            properties = self.enrich_params({
                "path": page_path,
                "title": page_title,
            })
            
            # Use RudderStack's page() method
            rudder.page(
                user_id=self._client_id,
                name=page_title,
                properties=properties
            )
            
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[RudderStack] Page tracked: {page_path}")
                
        except Exception as e:
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[RudderStack] Failed to track page: {e}")
    
    def track_event(self, event_name: str, params: Optional[Dict[str, Any]] = None) -> None:
        """
        Track a custom event to RudderStack.
        
        RudderStack will route this event to all configured downstream
        destinations (GA4, Amplitude, Mixpanel, etc.).
        
        Args:
            event_name: Name of the event (e.g., "workflow_started")
            params: Optional dictionary of event properties
        """
        if not self.is_enabled or not self._initialized:
            return
        
        # Enrich parameters with common metadata
        enriched_params = self.enrich_params(params)
        
        # Send to RudderStack
        self._send_to_provider({
            'event_name': event_name,
            'properties': enriched_params
        })
    
    def _send_to_provider(self, payload: Dict[str, Any]) -> None:
        """
        Send event to RudderStack.
        
        Args:
            payload: Dictionary with 'event_name' and 'properties'
        """
        try:
            event_name = payload['event_name']
            properties = payload['properties']
            
            # Use RudderStack's track() method
            rudder.track(
                user_id=self._client_id,
                event=event_name,
                properties=properties
            )
            
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[RudderStack] Event sent: {event_name}")
                
        except Exception as e:
            # Fail silently - telemetry should never break the app
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[RudderStack] Failed to send event: {e}")
    
    def flush(self) -> None:
        """
        Flush any pending events to RudderStack.
        
        Call this before app shutdown to ensure all events are sent.
        """
        if self._initialized:
            try:
                rudder.flush()
                if os.getenv("DEBUG_TELEMETRY"):
                    print("[RudderStack] Flushed pending events")
            except Exception as e:
                if os.getenv("DEBUG_TELEMETRY"):
                    print(f"[RudderStack] Failed to flush: {e}")
    
    def shutdown(self) -> None:
        """
        Shutdown RudderStack client gracefully.
        
        Flushes pending events and closes the connection.
        """
        if self._initialized:
            try:
                rudder.shutdown()
                if os.getenv("DEBUG_TELEMETRY"):
                    print("[RudderStack] Shutdown complete")
            except Exception as e:
                if os.getenv("DEBUG_TELEMETRY"):
                    print(f"[RudderStack] Failed to shutdown: {e}")
    
    @property
    def is_enabled(self) -> bool:
        """Check if RudderStack provider is enabled and SDK is available."""
        return RUDDERSTACK_AVAILABLE and super().is_enabled
