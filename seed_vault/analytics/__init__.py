"""
Analytics module for Seed Vault.

Provides telemetry tracking with RudderStack integration
and SQLite-persistent client IDs.
"""

# Base classes and configs
from .base_telemetry import (
    BaseTelemetryProvider,
    TelemetryContext,
    ProviderConfig,
    RudderStackConfig
)

# Provider implementations
from .rudderstack_provider import RudderStackTelemetryProvider

# Manager and convenience functions
from .telemetry_manager import TelemetryManager, init_telemetry

# Main exports
__all__ = [
    # Manager (primary interface)
    "TelemetryManager",
    "TelemetryClient",  # Alias for backward compatibility
    "init_telemetry",
    
    # Base classes
    "BaseTelemetryProvider",
    "TelemetryContext",
    
    # Configs
    "ProviderConfig",
    "RudderStackConfig",
    
    # Providers
    "RudderStackTelemetryProvider",
]

# Alias for backward compatibility
TelemetryClient = TelemetryManager
