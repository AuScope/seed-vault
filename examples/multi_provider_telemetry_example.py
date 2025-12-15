"""
Multi-Provider Telemetry Example for Seed Vault

Demonstrates the new base telemetry system with both GA4 and Amplitude providers.

To run this example:
1. Copy .env.example to .env
2. Fill in your GA4 and/or Amplitude credentials
3. Run: python examples/multi_provider_telemetry_example.py
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from seed_vault.analytics import (
    TelemetryManager,
    GA4Config,
    AmplitudeConfig
)


def example_automatic_initialization():
    """
    Example 1: Automatic initialization from environment variables.
    
    This is the recommended approach - just set environment variables
    and the manager will auto-detect and initialize available providers.
    """
    print("=" * 60)
    print("Example 1: Automatic Initialization")
    print("=" * 60)
    
    # Create a minimal settings object
    class MockSettings:
        analytics_enabled = True
    
    settings = MockSettings()
    
    # Initialize from settings and environment
    manager = TelemetryManager.from_settings(
        settings=settings,
        db_path="SVdata/database.sqlite"
    )
    
    print(f"✓ Manager initialized")
    print(f"  Enabled providers: {manager.enabled_providers}")
    print(f"  Client ID: {manager.get_client_id()}")
    print(f"  Session ID: {manager.get_session_id()}")
    print()
    
    # Track some events
    print("Tracking events...")
    
    # Page view
    manager.track_page_view("/example-page", "Example Page")
    print("  ✓ Page view tracked")
    
    # Custom event
    manager.track_event("example_event", {
        "example_param": "value",
        "number_param": 42
    })
    print("  ✓ Custom event tracked")
    
    # Flush any pending events (important for Amplitude)
    manager.flush()
    print("  ✓ Events flushed")
    print()


def example_explicit_configuration():
    """
    Example 2: Explicit provider configuration.
    
    Use this when you want fine-grained control over which providers
    are enabled and their configuration.
    """
    print("=" * 60)
    print("Example 2: Explicit Configuration")
    print("=" * 60)
    
    # Create configurations explicitly
    ga4_config = GA4Config(
        enabled=True,
        measurement_id=os.getenv("GA_MEASUREMENT_ID"),
        api_secret=os.getenv("GA_API_SECRET")
    )
    
    amplitude_config = AmplitudeConfig(
        enabled=True,
        api_key=os.getenv("AMPLITUDE_API_KEY")
    )
    
    # Check validity
    print(f"GA4 config valid: {ga4_config.is_valid()}")
    print(f"Amplitude config valid: {amplitude_config.is_valid()}")
    print()
    
    # Create manager with explicit configs
    manager = TelemetryManager.from_configs(
        db_path="SVdata/database.sqlite",
        analytics_enabled=True,
        ga4_config=ga4_config,
        amplitude_config=amplitude_config
    )
    
    print(f"✓ Manager initialized with explicit configs")
    print(f"  Enabled providers: {manager.enabled_providers}")
    print()


def example_selective_providers():
    """
    Example 3: Enable only specific providers.
    
    Shows how to enable GA4 only or Amplitude only.
    """
    print("=" * 60)
    print("Example 3: Selective Providers (GA4 Only)")
    print("=" * 60)
    
    # Enable only GA4
    manager = TelemetryManager.from_configs(
        db_path="SVdata/database.sqlite",
        analytics_enabled=True,
        ga4_config=GA4Config(
            enabled=True,
            measurement_id=os.getenv("GA_MEASUREMENT_ID"),
            api_secret=os.getenv("GA_API_SECRET")
        ),
        amplitude_config=None  # Don't use Amplitude
    )
    
    print(f"✓ GA4-only manager initialized")
    print(f"  Enabled providers: {manager.enabled_providers}")
    
    # Track an event (goes only to GA4)
    manager.track_event("ga4_only_event", {"test": True})
    print("  ✓ Event sent to GA4 only")
    print()


def example_workflow_tracking():
    """
    Example 4: Real-world workflow tracking.
    
    Demonstrates tracking a complete user workflow with multiple steps.
    """
    print("=" * 60)
    print("Example 4: Workflow Tracking")
    print("=" * 60)
    
    class MockSettings:
        analytics_enabled = True
    
    manager = TelemetryManager.from_settings(
        MockSettings(),
        "SVdata/database.sqlite"
    )
    
    print("Simulating event-based workflow...")
    print()
    
    # User lands on workflow selection
    manager.track_page_view("/main-flows/workflow-selection", "Workflow Selection")
    print("  ✓ Page: Workflow Selection")
    
    # User starts event-based workflow
    manager.track_event("workflow_started", {
        "workflow_type": "event_based",
        "download_type": "waveform"
    })
    print("  ✓ Event: workflow_started")
    
    # Step 1: Event search
    manager.track_page_view("/main-flows/step1-event-search", "Event Search")
    print("  ✓ Page: Event Search")
    
    manager.track_event("workflow_step_completed", {
        "step": 1,
        "step_name": "event_search",
        "workflow_type": "event_based",
        "num_events_found": 15
    })
    print("  ✓ Event: Step 1 completed")
    
    # Step 2: Station search
    manager.track_page_view("/main-flows/step2-station-search", "Station Search")
    print("  ✓ Page: Station Search")
    
    manager.track_event("workflow_step_completed", {
        "step": 2,
        "step_name": "station_search",
        "workflow_type": "event_based",
        "num_stations_found": 42
    })
    print("  ✓ Event: Step 2 completed")
    
    # Step 3: Waveform download
    manager.track_page_view("/main-flows/step3-waveform-download", "Waveform Download")
    print("  ✓ Page: Waveform Download")
    
    manager.track_event("workflow_completed", {
        "success": True,
        "workflow_type": "event_based",
        "num_stations": 42,
        "num_events": 15,
        "duration_seconds": 125,
        "data_size_mb": 234.5
    })
    print("  ✓ Event: Workflow completed")
    
    manager.flush()
    print()
    print("✓ Workflow tracking complete!")
    print()


def example_error_handling():
    """
    Example 5: Graceful error handling.
    
    Shows that analytics failures don't break your app.
    """
    print("=" * 60)
    print("Example 5: Error Handling")
    print("=" * 60)
    
    # Initialize with invalid config (will fail gracefully)
    manager = TelemetryManager.from_configs(
        db_path="SVdata/database.sqlite",
        analytics_enabled=True,
        ga4_config=GA4Config(
            enabled=True,
            measurement_id="INVALID",
            api_secret="INVALID"
        ),
        amplitude_config=None
    )
    
    print("✓ Manager initialized with invalid credentials")
    print(f"  Is enabled: {manager.is_enabled}")
    print(f"  Enabled providers: {manager.enabled_providers}")
    print()
    
    # Try to track (will fail silently)
    print("Attempting to track event with invalid config...")
    manager.track_event("test_event", {"test": True})
    print("  ✓ No error raised - app continues normally!")
    print()
    
    print("This demonstrates that telemetry failures don't crash your app.")
    print()


def example_disabled_analytics():
    """
    Example 6: Disabled analytics.
    
    Shows what happens when user disables analytics.
    """
    print("=" * 60)
    print("Example 6: Disabled Analytics")
    print("=" * 60)
    
    class MockSettings:
        analytics_enabled = False  # User disabled analytics
    
    manager = TelemetryManager.from_settings(
        MockSettings(),
        "SVdata/database.sqlite"
    )
    
    print(f"✓ Manager initialized with analytics disabled")
    print(f"  Is enabled: {manager.is_enabled}")
    print(f"  Enabled providers: {manager.enabled_providers}")
    print()
    
    # Try to track (nothing will be sent)
    print("Attempting to track event...")
    manager.track_event("test_event", {"test": True})
    print("  ✓ Event NOT sent (respects user preference)")
    print()


def main():
    """Run all examples."""
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 10 + "Multi-Provider Telemetry Examples" + " " * 15 + "║")
    print("╚" + "═" * 58 + "╝")
    print("\n")
    
    # Enable debug mode to see what's happening
    os.environ['DEBUG_TELEMETRY'] = '1'
    
    # Check if environment is configured
    has_ga4 = bool(os.getenv("GA_MEASUREMENT_ID") and os.getenv("GA_API_SECRET"))
    has_amplitude = bool(os.getenv("AMPLITUDE_API_KEY"))
    
    print("Environment Check:")
    print(f"  GA4 configured: {'✓' if has_ga4 else '✗'}")
    print(f"  Amplitude configured: {'✓' if has_amplitude else '✗'}")
    print()
    
    if not (has_ga4 or has_amplitude):
        print("⚠️  No providers configured!")
        print("   Please set up .env file with GA4 and/or Amplitude credentials.")
        print("   See .env.example for template.")
        print()
    
    # Run examples
    example_automatic_initialization()
    example_explicit_configuration()
    example_selective_providers()
    example_workflow_tracking()
    example_error_handling()
    example_disabled_analytics()
    
    print("=" * 60)
    print("All examples completed!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Check GA4 DebugView for real-time events")
    print("  2. Check Amplitude User Lookup for event stream")
    print("  3. Review TELEMETRY_QUICKSTART.md for usage guide")
    print("  4. Review TELEMETRY_ARCHITECTURE.md for technical details")
    print()


if __name__ == "__main__":
    main()
