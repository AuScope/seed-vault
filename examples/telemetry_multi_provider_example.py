"""
Multi-Provider Telemetry Example for Seed Vault

Demonstrates how to use the new telemetry system with multiple analytics
providers (GA4 and Amplitude) simultaneously.
"""

import os
from pathlib import Path

# Set up environment variables (normally in .env file)
os.environ['GA_MEASUREMENT_ID'] = 'G-XXXXXXXXXX'
os.environ['GA_API_SECRET'] = 'your_ga4_secret'
os.environ['AMPLITUDE_API_KEY'] = 'your_amplitude_key'
os.environ['DEBUG_TELEMETRY'] = '1'  # Enable debug output

from seed_vault.analytics import (
    TelemetryManager,
    GA4Config,
    AmplitudeConfig,
    TelemetryContext
)
from seed_vault.models.config import SeismoLoaderSettings


def example_1_from_settings():
    """
    Example 1: Initialize from SeismoLoaderSettings (recommended)
    
    This is the standard way used in the Streamlit app.
    Automatically detects and enables providers based on environment variables.
    """
    print("\n=== Example 1: Initialize from Settings ===\n")
    
    # Load settings (or create default)
    settings = SeismoLoaderSettings()
    settings.analytics_enabled = True
    
    # Initialize telemetry manager
    db_path = "SVdata/database.sqlite"
    telemetry = TelemetryManager.from_settings(settings, db_path)
    
    # Check which providers are enabled
    print(f"Enabled providers: {telemetry.enabled_providers}")
    print(f"Client ID: {telemetry.get_client_id()}")
    print(f"Session ID: {telemetry.get_session_id()}")
    
    # Track page view - goes to all enabled providers
    telemetry.track_page_view("/example-page", "Example Page")
    
    # Track custom event - goes to all enabled providers
    telemetry.track_event("example_event", {
        "example_param": "value",
        "count": 42
    })
    
    print("\n✓ Events sent to all enabled providers")


def example_2_explicit_config():
    """
    Example 2: Initialize with explicit provider configs
    
    Useful when you want fine-grained control over which providers
    are enabled and their configurations.
    """
    print("\n=== Example 2: Explicit Configuration ===\n")
    
    # Configure GA4
    ga4_config = GA4Config(
        enabled=True,
        measurement_id=os.getenv('GA_MEASUREMENT_ID'),
        api_secret=os.getenv('GA_API_SECRET')
    )
    
    # Configure Amplitude
    amplitude_config = AmplitudeConfig(
        enabled=True,
        api_key=os.getenv('AMPLITUDE_API_KEY')
    )
    
    # Create manager with explicit configs
    telemetry = TelemetryManager.from_configs(
        db_path="SVdata/database.sqlite",
        analytics_enabled=True,
        ga4_config=ga4_config,
        amplitude_config=amplitude_config
    )
    
    print(f"Enabled providers: {telemetry.enabled_providers}")
    
    # Track events
    telemetry.track_page_view("/explicit-config", "Explicit Config Example")
    telemetry.track_event("config_test", {"method": "explicit"})
    
    print("\n✓ Events sent with explicit configuration")


def example_3_selective_providers():
    """
    Example 3: Enable only specific providers
    
    Shows how to enable GA4 but not Amplitude, or vice versa.
    """
    print("\n=== Example 3: Selective Providers (GA4 only) ===\n")
    
    # Enable only GA4
    ga4_config = GA4Config(
        enabled=True,
        measurement_id=os.getenv('GA_MEASUREMENT_ID'),
        api_secret=os.getenv('GA_API_SECRET')
    )
    
    # Disable Amplitude
    amplitude_config = AmplitudeConfig(
        enabled=False
    )
    
    telemetry = TelemetryManager.from_configs(
        db_path="SVdata/database.sqlite",
        analytics_enabled=True,
        ga4_config=ga4_config,
        amplitude_config=amplitude_config
    )
    
    print(f"Enabled providers: {telemetry.enabled_providers}")
    
    telemetry.track_page_view("/ga4-only", "GA4 Only Example")
    telemetry.track_event("selective_test", {"provider": "ga4"})
    
    print("\n✓ Events sent to GA4 only")


def example_4_individual_providers():
    """
    Example 4: Use individual providers directly
    
    Advanced usage - directly instantiate and use specific providers.
    Useful for testing or when you need provider-specific features.
    """
    print("\n=== Example 4: Individual Providers ===\n")
    
    from seed_vault.analytics import GA4TelemetryProvider, AmplitudeTelemetryProvider
    
    # Create shared context
    context = TelemetryContext(
        db_path="SVdata/database.sqlite",
        analytics_enabled=True
    )
    
    print(f"Shared Client ID: {context.client_id}")
    print(f"Shared Session ID: {context.session_id}")
    print(f"Runtime: {context.runtime}")
    
    # Create GA4 provider
    ga4_config = GA4Config(
        enabled=True,
        measurement_id=os.getenv('GA_MEASUREMENT_ID'),
        api_secret=os.getenv('GA_API_SECRET')
    )
    
    ga4_provider = GA4TelemetryProvider(
        config=ga4_config,
        db_path=context.db_path,
        client_id=context.client_id,
        session_id=context.session_id,
        runtime=context.runtime
    )
    
    # Create Amplitude provider
    amplitude_config = AmplitudeConfig(
        enabled=True,
        api_key=os.getenv('AMPLITUDE_API_KEY')
    )
    
    amplitude_provider = AmplitudeTelemetryProvider(
        config=amplitude_config,
        db_path=context.db_path,
        client_id=context.client_id,
        session_id=context.session_id,
        runtime=context.runtime
    )
    
    # Use providers individually
    print("\nTracking to GA4:")
    ga4_provider.track_page_view("/individual-ga4", "Individual GA4")
    ga4_provider.track_event("ga4_specific", {"feature": "custom"})
    
    print("\nTracking to Amplitude:")
    amplitude_provider.track_page_view("/individual-amplitude", "Individual Amplitude")
    amplitude_provider.track_event("amplitude_specific", {"feature": "custom"})
    
    # Flush Amplitude events (recommended before shutdown)
    amplitude_provider.flush()
    
    print("\n✓ Providers used individually")


def example_5_workflow_tracking():
    """
    Example 5: Real-world workflow tracking
    
    Demonstrates tracking a complete workflow with multiple steps,
    similar to how it's used in the actual Streamlit app.
    """
    print("\n=== Example 5: Workflow Tracking ===\n")
    
    settings = SeismoLoaderSettings()
    settings.analytics_enabled = True
    
    telemetry = TelemetryManager.from_settings(settings, "SVdata/database.sqlite")
    
    print(f"Tracking workflow with providers: {telemetry.enabled_providers}\n")
    
    # User arrives at main page
    telemetry.track_page_view("/main-flows", "Main Flows")
    
    # User selects workflow
    telemetry.track_page_view("/main-flows/workflow-selection", "Workflow Selection")
    
    # User starts event-based workflow
    telemetry.track_event("workflow_started", {
        "workflow_type": "event_based",
        "download_type": "waveform"
    })
    
    # Step 1: Event search
    telemetry.track_page_view("/main-flows/step1-event-search", "Step 1: Event Search")
    telemetry.track_event("workflow_step_completed", {
        "step": 1,
        "step_name": "event_search",
        "workflow_type": "event_based"
    })
    
    # Step 2: Station search
    telemetry.track_page_view("/main-flows/step2-station-search", "Step 2: Station Search")
    telemetry.track_event("workflow_step_completed", {
        "step": 2,
        "step_name": "station_search",
        "workflow_type": "event_based"
    })
    
    # Step 3: Waveform download
    telemetry.track_page_view("/main-flows/step3-waveform-download", "Step 3: Waveform Download")
    
    # Workflow completes
    telemetry.track_event("workflow_completed", {
        "workflow_type": "event_based",
        "success": True,
        "total_steps": 3
    })
    
    # Flush pending events
    telemetry.flush()
    
    print("\n✓ Complete workflow tracked")


def example_6_error_handling():
    """
    Example 6: Error handling and graceful degradation
    
    Shows how the system handles missing configurations, SDK issues, etc.
    """
    print("\n=== Example 6: Error Handling ===\n")
    
    # Scenario 1: Analytics disabled
    print("Scenario 1: Analytics disabled")
    settings = SeismoLoaderSettings()
    settings.analytics_enabled = False
    
    telemetry = TelemetryManager.from_settings(settings, "SVdata/database.sqlite")
    print(f"Enabled providers: {telemetry.enabled_providers}")
    print(f"Is enabled: {telemetry.is_enabled}")
    
    # These calls do nothing but don't break the app
    telemetry.track_page_view("/test", "Test")
    telemetry.track_event("test_event", {})
    print("✓ Tracking calls safely ignored when disabled\n")
    
    # Scenario 2: Invalid configuration
    print("Scenario 2: Invalid GA4 config (missing api_secret)")
    ga4_config = GA4Config(
        enabled=True,
        measurement_id="G-XXXXXXXXXX",
        api_secret=None  # Missing!
    )
    print(f"Config is valid: {ga4_config.is_valid()}")
    
    telemetry = TelemetryManager.from_configs(
        db_path="SVdata/database.sqlite",
        analytics_enabled=True,
        ga4_config=ga4_config
    )
    print(f"Enabled providers: {telemetry.enabled_providers}")
    print("✓ Invalid configs are safely ignored\n")
    
    # Scenario 3: Amplitude SDK not installed (simulated)
    print("Scenario 3: Missing Amplitude SDK")
    print("(If SDK is not installed, provider gracefully disables)")
    amplitude_config = AmplitudeConfig(
        enabled=True,
        api_key="test-key"
    )
    # Provider will check AMPLITUDE_AVAILABLE flag and disable if SDK missing
    print("✓ Missing SDK handled gracefully\n")


def main():
    """Run all examples."""
    print("=" * 70)
    print("Seed Vault Multi-Provider Telemetry Examples")
    print("=" * 70)
    
    try:
        example_1_from_settings()
        example_2_explicit_config()
        example_3_selective_providers()
        example_4_individual_providers()
        example_5_workflow_tracking()
        example_6_error_handling()
        
        print("\n" + "=" * 70)
        print("All examples completed successfully!")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
