"""
Amplitude provider for Seed Vault Analytics.

Implements Amplitude Analytics SDK with event tracking and user properties.
"""

import os
from typing import Optional, Dict, Any

try:
    from amplitude import Amplitude, BaseEvent, EventOptions, Identify
    AMPLITUDE_AVAILABLE = True
except ImportError:
    AMPLITUDE_AVAILABLE = False

from .base_telemetry import BaseTelemetryProvider, AmplitudeConfig


class AmplitudeTelemetryProvider(BaseTelemetryProvider):
    """
    Amplitude telemetry provider.
    
    Features:
    - Amplitude Analytics SDK integration
    - Page view tracking as custom events
    - Custom event tracking with properties
    - User properties for runtime context
    - Graceful fallback if SDK not installed
    
    Example:
        >>> from seed_vault.analytics import AmplitudeTelemetryProvider, AmplitudeConfig, TelemetryContext
        >>> 
        >>> config = AmplitudeConfig(
        ...     enabled=True,
        ...     api_key="your-amplitude-api-key"
        ... )
        >>> context = TelemetryContext(db_path="SVdata/database.sqlite")
        >>> 
        >>> provider = AmplitudeTelemetryProvider(
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
        config: AmplitudeConfig,
        db_path: str,
        client_id: str,
        session_id: str,
        runtime: str
    ):
        """
        Initialize Amplitude provider.
        
        Args:
            config: AmplitudeConfig instance with api_key
            db_path: Path to SQLite database
            client_id: Persistent UUID for user tracking
            session_id: Session-specific UUID (becomes Amplitude session_id)
            runtime: Runtime environment ("streamlit" or "cli")
        """
        super().__init__(config, db_path, client_id, session_id, runtime)
        self.config: AmplitudeConfig = config  # Type hint for IDE support
        self._amplitude_client: Optional[Amplitude] = None
        
        if not AMPLITUDE_AVAILABLE:
            if os.getenv("DEBUG_TELEMETRY"):
                print("[Amplitude] SDK not installed. Install with: poetry add amplitude-analytics")
            return
        
        if self.is_enabled:
            self._init_amplitude()
    
    def _init_amplitude(self) -> None:
        """Initialize the Amplitude SDK client."""
        try:
            self._amplitude_client = Amplitude(self.config.api_key)
            
            # Set user properties for context
            identify = Identify()
            identify.set("runtime", self._runtime)
            identify.set("lib_version", self.LIBRARY_VERSION)
            
            self._amplitude_client.identify(
                identify,
                EventOptions(user_id=self._client_id)
            )
            
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Amplitude] Initialized with client_id: {self._client_id}")
                
        except Exception as e:
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Amplitude] Failed to initialize: {e}")
            self._amplitude_client = None
    
    def track_page_view(self, page_path: str, page_title: str) -> None:
        """
        Track a page view as a custom event.
        
        Amplitude doesn't have a built-in page_view event, so we track it
        as a custom "Page Viewed" event with path and title properties.
        
        Args:
            page_path: Virtual page path (e.g., "/event-search")
            page_title: Human-readable page title (e.g., "Event Search")
        """
        if not self.is_enabled or not self._amplitude_client:
            return
        
        self.track_event("Page Viewed", {
            "page_path": page_path,
            "page_title": page_title,
        })
    
    def track_event(self, event_name: str, params: Optional[Dict[str, Any]] = None) -> None:
        """
        Track a custom event to Amplitude.
        
        Args:
            event_name: Name of the event (e.g., "workflow_started")
            params: Optional dictionary of event properties
        """
        if not self.is_enabled or not self._amplitude_client:
            return
        
        # Enrich parameters with common metadata
        enriched_params = self.enrich_params(params)
        
        # Create Amplitude event
        event = BaseEvent(
            event_type=event_name,
            user_id=self._client_id,
            session_id=int(hash(self._session_id) % (10 ** 9)),  # Amplitude wants numeric session_id
            event_properties=enriched_params
        )
        
        # Send to Amplitude
        self._send_to_provider(event)
    
    def _send_to_provider(self, event: Any) -> None:
        """
        Send event to Amplitude.
        
        Args:
            event: BaseEvent instance to send to Amplitude
        """
        try:
            self._amplitude_client.track(event)
            
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Amplitude] Event sent: {event.event_type}")
                
        except Exception as e:
            # Fail silently - telemetry should never break the app
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Amplitude] Failed to send event: {e}")
    
    def flush(self) -> None:
        """
        Flush any pending events to Amplitude.
        
        Call this before app shutdown to ensure all events are sent.
        """
        if self._amplitude_client:
            try:
                self._amplitude_client.flush()
                if os.getenv("DEBUG_TELEMETRY"):
                    print("[Amplitude] Flushed pending events")
            except Exception as e:
                if os.getenv("DEBUG_TELEMETRY"):
                    print(f"[Amplitude] Failed to flush: {e}")
    
    @property
    def is_enabled(self) -> bool:
        """Check if Amplitude provider is enabled and SDK is available."""
        return AMPLITUDE_AVAILABLE and super().is_enabled
