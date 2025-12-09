"""
Example usage of the TelemetryClient for Seed Vault analytics.

This demonstrates how to integrate telemetry tracking into the application.
"""

from seed_vault.analytics import TelemetryClient, init_telemetry
from seed_vault.models.config import SeismoLoaderSettings


def example_basic_usage():
    """Basic telemetry usage example."""
    
    # Load settings from config file
    settings = SeismoLoaderSettings.from_cfg_file("seed_vault/service/config.cfg")
    
    # Initialize telemetry client
    # Uses the same database as the app for persistent client_id
    telemetry = TelemetryClient(settings, db_path="SVdata/database.sqlite")
    
    # Check if telemetry is enabled
    if telemetry.is_enabled:
        print("✅ Telemetry is enabled")
        print(f"   Client ID: {telemetry.get_client_id()}")
        print(f"   Session ID: {telemetry.get_session_id()}")
    else:
        print("❌ Telemetry is disabled or not configured")
        print("   Set GA_MEASUREMENT_ID and GA_API_SECRET in .env file")
        return
    
    # Track virtual page views for multi-step flows
    # Even though the app runs on a single URL, we track logical screens
    telemetry.track_page_view("/event-search", "Event Search")
    print("📊 Tracked page view: Event Search")
    
    # Track custom events
    telemetry.track_event("flow_started", {
        "flow_type": "event_based",
        "network": "IU"
    })
    print("📊 Tracked event: flow_started")


def example_streamlit_integration():
    """Example of integrating telemetry in Streamlit app."""
    
    # In your Streamlit app (e.g., main_flows.py)
    settings = SeismoLoaderSettings.from_cfg_file("seed_vault/service/config.cfg")
    telemetry = init_telemetry(settings, db_path="SVdata/database.sqlite")
    
    # Track when user enters a workflow step
    telemetry.track_page_view("/main-flows/event-search", "Main Flows - Event Search")
    
    # Track user actions
    telemetry.track_event("event_search_submitted", {
        "min_magnitude": 5.5,
        "max_magnitude": 7.0,
        "time_range_days": 30,
    })
    
    # Track when user moves to next step
    telemetry.track_page_view("/main-flows/station-search", "Main Flows - Station Search")
    
    # Track workflow completion
    telemetry.track_event("workflow_completed", {
        "flow_type": "event_based",
        "num_events": 10,
        "num_stations": 25,
        "total_duration_seconds": 180,
    })


def example_cli_integration():
    """Example of integrating telemetry in CLI."""
    
    # In CLI code
    settings = SeismoLoaderSettings.from_cfg_file("seed_vault/service/config.cfg")
    telemetry = TelemetryClient(settings, db_path="SVdata/database.sqlite")
    
    # Track CLI command execution
    telemetry.track_event("cli_command", {
        "command": "download",
        "args": "--network IU --station ANMO"
    })
    
    # Track download progress
    telemetry.track_event("download_started", {
        "data_type": "waveform",
        "num_stations": 1
    })
    
    telemetry.track_event("download_completed", {
        "data_type": "waveform", 
        "num_stations": 1,
        "duration_seconds": 45,
        "success": True
    })


def example_error_tracking():
    """Example of tracking errors and exceptions."""
    
    settings = SeismoLoaderSettings.from_cfg_file("seed_vault/service/config.cfg")
    telemetry = TelemetryClient(settings, db_path="SVdata/database.sqlite")
    
    try:
        # Some operation that might fail
        pass
    except Exception as e:
        # Track the error (don't send sensitive data)
        telemetry.track_event("error_occurred", {
            "error_type": type(e).__name__,
            "error_context": "event_search",
            "error_message": str(e)[:100]  # Truncate to avoid sending too much data
        })
        raise


def example_feature_usage():
    """Example of tracking feature usage."""
    
    settings = SeismoLoaderSettings.from_cfg_file("seed_vault/service/config.cfg")
    telemetry = TelemetryClient(settings, db_path="SVdata/database.sqlite")
    
    # Track when user uses map features
    telemetry.track_event("map_interaction", {
        "action": "draw_circle",
        "tool": "geometry_filter"
    })
    
    # Track export actions
    telemetry.track_event("data_export", {
        "format": "xml",
        "data_type": "stations",
        "num_records": 50
    })
    
    # Track settings changes
    telemetry.track_event("settings_changed", {
        "setting": "analytics_enabled",
        "new_value": False
    })


if __name__ == "__main__":
    print("=" * 60)
    print("Seed Vault Telemetry Examples")
    print("=" * 60)
    print()
    
    # Run basic example
    example_basic_usage()
    
    print()
    print("-" * 60)
    print("See source code for more examples:")
    print("  - Streamlit integration")
    print("  - CLI integration")
    print("  - Error tracking")
    print("  - Feature usage tracking")
    print("-" * 60)
