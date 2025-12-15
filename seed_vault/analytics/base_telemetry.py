"""
Base telemetry abstraction layer for Seed Vault Analytics.

Provides a common interface for multiple analytics providers (GA4, Amplitude, etc.)
with shared functionality for client/session management and event tracking.
"""

import os
import sys
import sqlite3
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from pathlib import Path


@dataclass
class ProviderConfig:
    """Base configuration for analytics providers."""
    enabled: bool
    provider_name: str = ""
    
    @abstractmethod
    def is_valid(self) -> bool:
        """Check if provider configuration is valid and can be used."""
        pass


@dataclass
class GA4Config(ProviderConfig):
    """Configuration for Google Analytics 4."""
    measurement_id: Optional[str] = None
    api_secret: Optional[str] = None
    
    def __post_init__(self):
        self.provider_name = "GA4"
    
    def is_valid(self) -> bool:
        """Check if GA4 configuration is valid."""
        return (
            self.enabled and
            self.measurement_id is not None and
            self.api_secret is not None and
            len(self.measurement_id) > 0 and
            len(self.api_secret) > 0
        )


@dataclass
class AmplitudeConfig(ProviderConfig):
    """Configuration for Amplitude."""
    api_key: Optional[str] = None
    
    def __post_init__(self):
        self.provider_name = "Amplitude"
    
    def is_valid(self) -> bool:
        """Check if Amplitude configuration is valid."""
        return (
            self.enabled and
            self.api_key is not None and
            len(self.api_key) > 0
        )


@dataclass
class MixpanelConfig(ProviderConfig):
    """Configuration for Mixpanel."""
    project_token: Optional[str] = None
    
    def __post_init__(self):
        self.provider_name = "Mixpanel"
    
    def is_valid(self) -> bool:
        """Check if Mixpanel configuration is valid."""
        return (
            self.enabled and
            self.project_token is not None and
            len(self.project_token) > 0
        )


class BaseTelemetryProvider(ABC):
    """
    Abstract base class for all analytics providers.
    
    Defines the common interface and shared functionality that all providers
    must implement. Providers are responsible for:
    - Tracking page views with virtual paths
    - Tracking custom events with parameters
    - Managing provider-specific API calls
    - Graceful error handling
    
    Shared functionality provided by base class:
    - Client ID persistence (SQLite)
    - Session ID generation
    - Runtime detection (Streamlit vs CLI)
    - Common parameter enrichment
    """
    
    LIBRARY_VERSION = "1.0.0"
    REQUEST_TIMEOUT = 2  # seconds
    
    def __init__(
        self,
        config: ProviderConfig,
        db_path: str,
        client_id: str,
        session_id: str,
        runtime: str
    ):
        """
        Initialize the base telemetry provider.
        
        Args:
            config: Provider-specific configuration
            db_path: Path to SQLite database (for metadata storage)
            client_id: Persistent UUID for user tracking
            session_id: Session-specific UUID
            runtime: Runtime environment ("streamlit" or "cli")
        """
        self.config = config
        self.db_path = db_path
        self._client_id = client_id
        self._session_id = session_id
        self._runtime = runtime
    
    @abstractmethod
    def track_page_view(self, page_path: str, page_title: str) -> None:
        """
        Track a page view with a virtual path.
        
        Args:
            page_path: Virtual page path (e.g., "/event-search")
            page_title: Human-readable page title (e.g., "Event Search")
        """
        pass
    
    @abstractmethod
    def track_event(self, event_name: str, params: Optional[Dict[str, Any]] = None) -> None:
        """
        Track a custom event.
        
        Args:
            event_name: Name of the event (e.g., "workflow_started")
            params: Optional dictionary of event parameters
        """
        pass
    
    @abstractmethod
    def _send_to_provider(self, payload: Dict[str, Any]) -> None:
        """
        Send data to the analytics provider's API.
        
        Args:
            payload: Provider-specific payload
        """
        pass
    
    def enrich_params(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Enrich event parameters with common metadata.
        
        Args:
            params: User-provided event parameters
        
        Returns:
            Enriched parameters with session_id, runtime, lib_version
        """
        if params is None:
            params = {}
        
        return {
            **params,
            "session_id": self._session_id,
            "runtime": self._runtime,
            "lib_version": self.LIBRARY_VERSION,
        }
    
    @property
    def is_enabled(self) -> bool:
        """Check if provider is enabled and properly configured."""
        return self.config.is_valid()
    
    @property
    def provider_name(self) -> str:
        """Get the provider name."""
        return self.config.provider_name
    
    def get_client_id(self) -> str:
        """Get the current client ID."""
        return self._client_id
    
    def get_session_id(self) -> str:
        """Get the current session ID."""
        return self._session_id


class TelemetryContext:
    """
    Manages shared telemetry context (client_id, session_id, runtime).
    
    This class handles the SQLite persistence of client_id and provides
    common context that all providers can share.
    """
    
    def __init__(self, db_path: str, analytics_enabled: bool = True):
        """
        Initialize telemetry context.
        
        Args:
            db_path: Path to SQLite database
            analytics_enabled: Whether analytics is enabled globally
        """
        self.db_path = db_path
        self.analytics_enabled = analytics_enabled
        self._client_id: Optional[str] = None
        self._session_id: str = str(uuid.uuid4())
        self._runtime: str = self._detect_runtime()
        
        if analytics_enabled:
            self._init_database()
            self._client_id = self._get_or_create_client_id()
    
    def _detect_runtime(self) -> str:
        """
        Detect whether running under Streamlit or CLI.
        
        Returns:
            "streamlit" if running under Streamlit, "cli" otherwise
        """
        if 'streamlit' in sys.modules:
            try:
                import streamlit as st
                _ = st.session_state
                return "streamlit"
            except:
                pass
        
        if any('streamlit' in arg.lower() for arg in sys.argv):
            return "streamlit"
        
        return "cli"
    
    def _init_database(self) -> None:
        """Initialize the analytics_metadata table in SQLite."""
        try:
            db_dir = Path(self.db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS analytics_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
                conn.commit()
        except Exception as e:
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Telemetry] Failed to initialize database: {e}")
    
    def _get_or_create_client_id(self) -> str:
        """Get persistent client_id from database or create a new one."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT value FROM analytics_metadata WHERE key = 'client_id'"
                )
                row = cursor.fetchone()
                
                if row:
                    return row[0]
                
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
            if os.getenv("DEBUG_TELEMETRY"):
                print(f"[Telemetry] Failed to get/create client_id: {e}")
            return str(uuid.uuid4())
    
    @property
    def client_id(self) -> Optional[str]:
        """Get the client ID."""
        return self._client_id
    
    @property
    def session_id(self) -> str:
        """Get the session ID."""
        return self._session_id
    
    @property
    def runtime(self) -> str:
        """Get the runtime environment."""
        return self._runtime
