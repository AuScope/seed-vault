"""
Analytics module for Seed Vault.

Provides telemetry tracking with GA4 integration and SQLite-persistent client IDs.
"""

from .telemetry import TelemetryClient

__all__ = ["TelemetryClient"]
