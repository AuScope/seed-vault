"""
Google Analytics 4 provider for Seed Vault Analytics.

Implements GA4 Measurement Protocol API with virtual page path tracking.
"""

import os
from typing import Optional, Dict, Any
import requests

from .base_telemetry import BaseTelemetryProvider, GA4Config


class GA4TelemetryProvider(BaseTelemetryProvider):
    """
    Google Analytics 4 telemetry provider.
    
    Features:
    - GA4 Measurement Protocol API integration
    - Virtual page path tracking for single-page apps
    - Custom event tracking with parameter enrichment
    - Graceful error handling
    
    Example:
        >>> from seed_vault.analytics import GA4TelemetryProvider, GA4Config, TelemetryContext
        >>> 
        >>> config = GA4Config(
        ...     enabled=True,
        ...     measurement_id="G-XXXXXXXXXX",
        ...     api_secret="your-api-secret"
        ... )
        >>> context = TelemetryContext(db_path="SVdata/database.sqlite")
        >>> 
        >>> provider = GA4TelemetryProvider(
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
    
    GA_ENDPOINT = "https://www.google-analytics.com/mp/collect"
    
    def __init__(
        self,
        config: GA4Config,
        db_path: str,
        client_id: str,
        session_id: str,
        runtime: str
    ):
        """
        Initialize GA4 provider.
        
        Args:
            config: GA4Config instance with measurement_id and api_secret
            db_path: Path to SQLite database
            client_id: Persistent UUID for user tracking
            session_id: Session-specific UUID
            runtime: Runtime environment ("streamlit" or "cli")
        """
        super().__init__(config, db_path, client_id, session_id, runtime)
        self.config: GA4Config = config  # Type hint for IDE support
    
    def track_page_view(self, page_path: str, page_title: str) -> None:
        """
        Track a page view with a virtual path.
        
        Creates a GA4 page_view event with a virtual URL. The app renders
        multiple logical screens on the same physical URL, so we use virtual
        paths to differentiate them in analytics.
        
        Args:
            page_path: Virtual page path (e.g., "/event-search")
            page_title: Human-readable page title (e.g., "Event Search")
        """
        if not self.is_enabled:
            return
        
        # Construct virtual URL
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
            event_name: Name of the event (e.g., "workflow_started")
            params: Optional dictionary of event parameters
        """
        if not self.is_enabled:
            return
        
        # Enrich parameters with common metadata
        enriched_params = self.enrich_params(params)
        
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
        self._send_to_provider(payload)
    
    def _send_to_provider(self, payload: Dict[str, Any]) -> None:
        """
        POST event payload to Google Analytics 4 Measurement Protocol.
        
        Args:
            payload: GA4 measurement protocol payload with client_id and events
        """
        try:
            url = (
                f"{self.GA_ENDPOINT}"
                f"?measurement_id={self.config.measurement_id}"
                f"&api_secret={self.config.api_secret}"
            )
            
            response = requests.post(
                url,
                json=payload,
                timeout=self.REQUEST_TIMEOUT,
                headers={"Content-Type": "application/json"}
            )
            
            # GA4 Measurement Protocol returns 204 on success
            if response.status_code not in (200, 204):
                if os.getenv("DEBUG_TELEMETRY"):
                    print(f"[GA4] API returned status {response.status_code}")
            
            if os.getenv("DEBUG_TELEMETRY"):
                event_name = payload['events'][0]['name']
                print(f"[GA4] Event sent: {event_name}")
                
        except requests.exceptions.Timeout:
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[GA4] Request timeout")
        except Exception as e:
            # Fail silently - telemetry should never break the app
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[GA4] Failed to send event: {e}")
