# Telemetry Quick Start Guide

## Installation

The base system requires no additional dependencies beyond what's already installed. To enable Amplitude support:

```bash
poetry add amplitude-analytics
```

## Configuration

### 1. Create `.env` file (copy from `.env.example`):

```bash
# Google Analytics 4
GA_MEASUREMENT_ID=G-XXXXXXXXXX
GA_API_SECRET=your_ga4_api_secret

# Amplitude
AMPLITUDE_API_KEY=your_amplitude_api_key

# Optional
DEBUG_TELEMETRY=1  # Enable debug output
```

### 2. Enable analytics in app settings

Users control this via the Settings → Analytics tab in the UI, or:

```python
settings.analytics_enabled = True
```

## Basic Usage

### Initialize (done once at app startup)

```python
from seed_vault.analytics import TelemetryManager

# Automatic initialization from environment variables
telemetry = TelemetryManager.from_settings(settings, db_path="SVdata/database.sqlite")

# Check what's enabled
print(f"Active providers: {telemetry.enabled_providers}")
# Output: ['GA4', 'Amplitude']
```

### Track Page Views

```python
# Track a virtual page view
telemetry.track_page_view("/event-search", "Event Search")
telemetry.track_page_view("/waveform-download", "Waveform Download")
```

### Track Custom Events

```python
# Simple event
telemetry.track_event("button_clicked")

# Event with parameters
telemetry.track_event("workflow_started", {
    "workflow_type": "event_based",
    "download_type": "waveform"
})

# More complex example
telemetry.track_event("workflow_completed", {
    "success": True,
    "workflow_type": "event_based",
    "num_stations": 5,
    "duration_seconds": 120,
    "data_size_mb": 45.2
})
```

## Streamlit Integration

### In your Streamlit app:

```python
from seed_vault.ui.app_pages.helpers.telemetry import (
    init_telemetry_client,
    track_page_view,
    track_event,
    get_telemetry_client
)

# Initialize once (usually in get_app_settings or main entry point)
telemetry = init_telemetry_client(settings, db_path)

# Track page views (automatically deduplicated on reruns)
track_page_view("/my-page", "My Page Title")

# Track events
track_event("user_action", {"action": "clicked_button"})

# Get the manager instance if needed
telemetry = get_telemetry_client()
if telemetry:
    print(f"Client ID: {telemetry.get_client_id()}")
```

### Important: Deduplication

The helper functions automatically handle Streamlit reruns:

```python
# This WON'T send duplicate events on rerun:
track_page_view("/same-page", "Same Page")
track_page_view("/same-page", "Same Page")  # Ignored (same page)

# This WILL send a new event:
track_page_view("/different-page", "Different Page")  # Tracked!
```

## Common Patterns

### Workflow Tracking

```python
# Start
track_event("workflow_started", {"workflow_type": "event_based"})

# Progress
track_event("workflow_step_completed", {
    "step": 1,
    "step_name": "event_search",
    "workflow_type": "event_based"
})

# Completion
track_event("workflow_completed", {
    "success": True,
    "workflow_type": "event_based",
    "duration_seconds": 45
})
```

### User Interactions

```python
# Button clicks
track_event("button_clicked", {"button": "start_download"})

# Form submissions
track_event("form_submitted", {"form": "station_search"})

# Settings changes
track_event("settings_changed", {"setting": "credentials"})
```

### Navigation

```python
# Main pages
track_page_view("/main-flows", "Main Workflows")
track_page_view("/db-explorer", "Database Explorer")

# Workflow stages
track_page_view("/main-flows/step1-event-search", "Event Search")
track_page_view("/main-flows/step2-station-search", "Station Search")

# Settings tabs
track_page_view("/settings/analytics", "Analytics Settings")
```

## Event Naming Conventions

### Page Views

- Use lowercase with dashes: `/event-search`, `/db-explorer`
- Use hierarchical paths: `/main-flows/step1-event-search`
- Be consistent across the app

### Custom Events

- Use snake_case: `workflow_started`, `button_clicked`
- Use past tense for completed actions: `workflow_completed`
- Be specific but concise: `analytics_preference_changed` not just `preference_changed`

### Event Parameters

- Use snake_case: `workflow_type`, `num_stations`
- Include context: `workflow_type` not just `type`
- Keep values simple: strings, numbers, booleans (no complex objects)

## Advanced Usage

### Manual Provider Configuration

```python
from seed_vault.analytics import (
    TelemetryManager,
    GA4Config,
    AmplitudeConfig
)

# Create custom configuration
manager = TelemetryManager.from_configs(
    db_path="SVdata/database.sqlite",
    analytics_enabled=True,
    ga4_config=GA4Config(
        enabled=True,
        measurement_id="G-XXXXXXXXXX",
        api_secret="secret"
    ),
    amplitude_config=AmplitudeConfig(
        enabled=False,  # Disable Amplitude
        api_key=None
    )
)
```

### Flush on Shutdown

For Amplitude, flush pending events before exit:

```python
# Before app shutdown
telemetry = get_telemetry_client()
if telemetry:
    telemetry.flush()
```

### Check Provider Status

```python
telemetry = get_telemetry_client()

# Check if any provider is enabled
if telemetry.is_enabled:
    print("Analytics is active")

# List enabled providers
print(f"Providers: {telemetry.enabled_providers}")
# Output: ['GA4', 'Amplitude']

# Get IDs
print(f"Client ID: {telemetry.get_client_id()}")
print(f"Session ID: {telemetry.get_session_id()}")
```

## Debugging

### Enable Debug Output

```bash
export DEBUG_TELEMETRY=1
streamlit run app.py
```

Output will show:

```
[TelemetryManager] Enabled providers: GA4, Amplitude
[GA4] Event sent: page_view
[Amplitude] Event sent: Page Viewed
```

### Common Issues

**No events showing up:**

1. Check `analytics_enabled` is `True`
2. Verify environment variables are set
3. Enable `DEBUG_TELEMETRY=1` to see errors
4. Check provider dashboards (GA4 DebugView, Amplitude User Lookup)

**Duplicate events:**

- Use the helper functions from `seed_vault.ui.app_pages.helpers.telemetry`
- They handle deduplication automatically

**Amplitude not working:**

- Check if SDK is installed: `poetry add amplitude-analytics`
- Verify API key is correct
- Check debug output for errors

## What Gets Tracked Automatically

When you initialize telemetry, all events include:

- `client_id` - Persistent anonymous user ID
- `session_id` - Current session ID
- `runtime` - "streamlit" or "cli"
- `lib_version` - Seed Vault version

You don't need to add these manually!

## Privacy & User Control

- All tracking is **anonymous** (no PII)
- Users can **disable analytics** in Settings → Analytics
- When disabled, no events are sent (not even initialization)
- Client ID is a **random UUID**, not linked to user identity
- We track **usage patterns only**, never:
  - User data
  - Seismic data
  - File paths
  - Credentials
  - Personal information

## Testing

### Test with Real Providers

```python
import os
os.environ['DEBUG_TELEMETRY'] = '1'

# Your tracking code here
telemetry.track_event("test_event", {"test": True})

# Check output for confirmation
```

### Verify in Dashboards

**Google Analytics 4:**

- Go to Admin → Data Streams → [Your Stream]
- Click "DebugView" to see events in real-time
- Events appear within seconds

**Amplitude:**

- Go to User Lookup
- Search for your client_id (printed in debug mode)
- View event stream in real-time

## Examples

See `examples/telemetry_example.py` for a complete working example.

## Need Help?

- See `TELEMETRY_ARCHITECTURE.md` for detailed technical documentation
- Check `TELEMETRY_IMPLEMENTATION.md` for implementation notes
- Review `TELEMETRY_TESTING_CHECKLIST.md` for testing guidance
