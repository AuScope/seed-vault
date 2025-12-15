"""
Unified telemetry manager for Seed Vault Analytics.

Manages multiple analytics providers simultaneously with a single interface.
"""

import os
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

from .base_telemetry import (
    BaseTelemetryProvider,
    TelemetryContext,
    GA4Config,
    AmplitudeConfig,
    MixpanelConfig
)
from .ga4_provider import GA4TelemetryProvider
from .amplitude_provider import AmplitudeTelemetryProvider
from .mixpanel_provider import MixpanelTelemetryProvider

# Load environment variables
load_dotenv()


class TelemetryManager:
    """
    Unified manager for multiple analytics providers.
    
    Handles initialization, configuration, and event routing to multiple
    analytics providers (GA4, Amplitude, etc.) simultaneously. Provides
    a single interface for tracking across all configured providers.
    
    Features:
    - Multi-provider support (send events to multiple services)
    - Shared client_id and session_id across providers
    - Automatic provider initialization based on config
    - Graceful handling of provider failures
    - Single API for all tracking operations
    
    Example:
        >>> from seed_vault.analytics import TelemetryManager
        >>> from seed_vault.models.config import SeismoLoaderSettings
        >>> 
        >>> settings = SeismoLoaderSettings.from_cfg_file("config.cfg")
        >>> manager = TelemetryManager.from_settings(settings, "SVdata/database.sqlite")
        >>> 
        >>> # Track to all enabled providers
        >>> manager.track_page_view("/event-search", "Event Search")
        >>> manager.track_event("workflow_started", {"workflow_type": "event_based"})
    """
    
    def __init__(
        self,
        providers: List[BaseTelemetryProvider],
        context: TelemetryContext
    ):
        """
        Initialize telemetry manager.
        
        Args:
            providers: List of initialized provider instances
            context: Shared telemetry context (client_id, session_id, etc.)
        """
        self.providers = providers
        self.context = context
        
        # Log enabled providers
        if os.getenv("DEBUG_TELEMETRY"):
            enabled = [p.provider_name for p in providers if p.is_enabled]
            print(f"[TelemetryManager] Enabled providers: {', '.join(enabled) if enabled else 'None'}")
    
    @classmethod
    def from_settings(cls, settings, db_path: str) -> "TelemetryManager":
        """
        Create TelemetryManager from SeismoLoaderSettings.
        
        Automatically initializes all configured providers based on
        environment variables and settings.
        
        Args:
            settings: SeismoLoaderSettings instance
            db_path: Path to SQLite database
        
        Returns:
            Initialized TelemetryManager instance
        """
        # Check if analytics is globally enabled
        analytics_enabled = getattr(settings, 'analytics_enabled', False)
        
        # Create shared context
        context = TelemetryContext(db_path=db_path, analytics_enabled=analytics_enabled)
        
        providers = []
        
        # Initialize GA4 provider
        ga4_config = GA4Config(
            enabled=analytics_enabled,
            measurement_id=os.getenv("GA_MEASUREMENT_ID"),
            api_secret=os.getenv("GA_API_SECRET")
        )
        
        if ga4_config.is_valid():
            ga4_provider = GA4TelemetryProvider(
                config=ga4_config,
                db_path=db_path,
                client_id=context.client_id,
                session_id=context.session_id,
                runtime=context.runtime
            )
            providers.append(ga4_provider)
        
        # Initialize Amplitude provider
        amplitude_config = AmplitudeConfig(
            enabled=analytics_enabled,
            api_key=os.getenv("AMPLITUDE_API_KEY")
        )
        
        if amplitude_config.is_valid():
            amplitude_provider = AmplitudeTelemetryProvider(
                config=amplitude_config,
                db_path=db_path,
                client_id=context.client_id,
                session_id=context.session_id,
                runtime=context.runtime
            )
            providers.append(amplitude_provider)
        
        # Initialize Mixpanel provider
        mixpanel_config = MixpanelConfig(
            enabled=analytics_enabled,
            project_token=os.getenv("MIXPANEL_PROJECT_TOKEN")
        )
        
        if mixpanel_config.is_valid():
            mixpanel_provider = MixpanelTelemetryProvider(
                config=mixpanel_config,
                db_path=db_path,
                client_id=context.client_id,
                session_id=context.session_id,
                runtime=context.runtime
            )
            providers.append(mixpanel_provider)
        
        return cls(providers, context)
    
    @classmethod
    def from_configs(
        cls,
        db_path: str,
        analytics_enabled: bool,
        ga4_config: Optional[GA4Config] = None,
        amplitude_config: Optional[AmplitudeConfig] = None,
        mixpanel_config: Optional[MixpanelConfig] = None
    ) -> "TelemetryManager":
        """
        Create TelemetryManager from explicit provider configs.
        
        Args:
            db_path: Path to SQLite database
            analytics_enabled: Whether analytics is globally enabled
            ga4_config: Optional GA4Config
            amplitude_config: Optional AmplitudeConfig
            mixpanel_config: Optional MixpanelConfig
        
        Returns:
            Initialized TelemetryManager instance
        """
        context = TelemetryContext(db_path=db_path, analytics_enabled=analytics_enabled)
        
        providers = []
        
        # Initialize GA4 if config provided
        if ga4_config and ga4_config.is_valid():
            providers.append(GA4TelemetryProvider(
                config=ga4_config,
                db_path=db_path,
                client_id=context.client_id,
                session_id=context.session_id,
                runtime=context.runtime
            ))
        
        # Initialize Amplitude if config provided
        if amplitude_config and amplitude_config.is_valid():
            providers.append(AmplitudeTelemetryProvider(
                config=amplitude_config,
                db_path=db_path,
                client_id=context.client_id,
                session_id=context.session_id,
                runtime=context.runtime
            ))
        
        # Initialize Mixpanel if config provided
        if mixpanel_config and mixpanel_config.is_valid():
            providers.append(MixpanelTelemetryProvider(
                config=mixpanel_config,
                db_path=db_path,
                client_id=context.client_id,
                session_id=context.session_id,
                runtime=context.runtime
            ))
        
        return cls(providers, context)
    
    def track_page_view(self, page_path: str, page_title: str) -> None:
        """
        Track a page view across all enabled providers.
        
        Args:
            page_path: Virtual page path (e.g., "/event-search")
            page_title: Human-readable page title (e.g., "Event Search")
        """
        for provider in self.providers:
            if provider.is_enabled:
                try:
                    provider.track_page_view(page_path, page_title)
                except Exception as e:
                    # Continue with other providers on failure
                    if os.getenv("DEBUG_TELEMETRY"):
                        print(f"[{provider.provider_name}] Failed to track page view: {e}")
    
    def track_event(self, event_name: str, params: Optional[Dict[str, Any]] = None) -> None:
        """
        Track a custom event across all enabled providers.
        
        Args:
            event_name: Name of the event (e.g., "workflow_started")
            params: Optional dictionary of event parameters
        """
        for provider in self.providers:
            if provider.is_enabled:
                try:
                    provider.track_event(event_name, params)
                except Exception as e:
                    # Continue with other providers on failure
                    if os.getenv("DEBUG_TELEMETRY"):
                        print(f"[{provider.provider_name}] Failed to track event: {e}")
    
    def flush(self) -> None:
        """
        Flush pending events for all providers.
        
        Call this before app shutdown to ensure all events are sent.
        """
        for provider in self.providers:
            if hasattr(provider, 'flush'):
                try:
                    provider.flush()
                except Exception as e:
                    if os.getenv("DEBUG_TELEMETRY"):
                        print(f"[{provider.provider_name}] Failed to flush: {e}")
    
    @property
    def is_enabled(self) -> bool:
        """Check if any provider is enabled."""
        return any(p.is_enabled for p in self.providers)
    
    @property
    def enabled_providers(self) -> List[str]:
        """Get list of enabled provider names."""
        return [p.provider_name for p in self.providers if p.is_enabled]
    
    def get_client_id(self) -> Optional[str]:
        """Get the shared client ID."""
        return self.context.client_id
    
    def get_session_id(self) -> str:
        """Get the shared session ID."""
        return self.context.session_id


# Backward compatibility alias
TelemetryClient = TelemetryManager


def init_telemetry(settings, db_path: str) -> TelemetryManager:
    """
    Helper function to initialize telemetry manager.
    
    Args:
        settings: SeismoLoaderSettings instance
        db_path: Path to SQLite database
    
    Returns:
        Initialized TelemetryManager instance
    
    Example:
        >>> from seed_vault.analytics import init_telemetry
        >>> from seed_vault.models.config import SeismoLoaderSettings
        >>> 
        >>> settings = SeismoLoaderSettings.from_cfg_file("config.cfg")
        >>> telemetry = init_telemetry(settings, "SVdata/database.sqlite")
    """
    return TelemetryManager.from_settings(settings, db_path)
