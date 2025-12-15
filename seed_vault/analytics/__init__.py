"""
Analytics module for Seed Vault.

Provides telemetry tracking with multi-provider support (GA4, Amplitude, Mixpanel, etc.)
and SQLite-persistent client IDs.
"""

# Base classes and configs
from .base_telemetry import (
    BaseTelemetryProvider,
    TelemetryContext,
    ProviderConfig,
    GA4Config,
    AmplitudeConfig,
    MixpanelConfig
)

# Provider implementations
from .ga4_provider import GA4TelemetryProvider
from .amplitude_provider import AmplitudeTelemetryProvider
from .mixpanel_provider import MixpanelTelemetryProvider

# Manager and convenience functions
from .telemetry_manager import TelemetryManager, init_telemetry

# Backward compatibility
from .telemetry import TelemetryClient as LegacyTelemetryClient

# Main exports
__all__ = [
    # Manager (primary interface)
    "TelemetryManager",
    "init_telemetry",
    
    # Base classes
    "BaseTelemetryProvider",
    "TelemetryContext",
    
    # Configs
    "ProviderConfig",
    "GA4Config",
    "AmplitudeConfig",
    "MixpanelConfig",
    
    # Providers
    "GA4TelemetryProvider",
    "AmplitudeTelemetryProvider",
    "MixpanelTelemetryProvider",
    
    # Backward compatibility (deprecated - use TelemetryManager)
    "TelemetryClient",
    "LegacyTelemetryClient",
]

# Alias for backward compatibility
TelemetryClient = TelemetryManager
