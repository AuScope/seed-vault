# Telemetry Quick Reference - Multi-Provider Edition

## 🚀 Quick Start

### 1. Install Dependencies

```bash
poetry add amplitude-analytics  # Already done!
```

### 2. Configure Environment

```bash
# .env file
GA_MEASUREMENT_ID=G-XXXXXXXXXX
GA_API_SECRET=your_ga4_secret
AMPLITUDE_API_KEY=your_amplitude_key
DEBUG_TELEMETRY=1  # Optional: enable debug output
```

### 3. Initialize (in your app)

```python
from seed_vault.analytics import TelemetryManager

telemetry = TelemetryManager.from_settings(settings, "SVdata/database.sqlite")
```

### 4. Track Events

```python
# Page view
telemetry.track_page_view("/page-path", "Page Title")

# Custom event
telemetry.track_event("event_name", {"param": "value"})
```

## 📦 Import Options

### Recommended (Multi-Provider)

```python
from seed_vault.analytics import TelemetryManager

telemetry = TelemetryManager.from_settings(settings, db_path)
```

### Backward Compatible

```python
from seed_vault.analytics import TelemetryClient  # Now alias to TelemetryManager

telemetry = TelemetryClient(settings, db_path)
```

### Streamlit Helpers (with deduplication)

```python
from seed_vault.ui.app_pages.helpers.telemetry import (
    init_telemetry_client,
    track_page_view,
    track_event
)
```

### Advanced (Individual Providers)

```python
from seed_vault.analytics import (
    GA4TelemetryProvider,
    AmplitudeTelemetryProvider,
    TelemetryContext,
    GA4Config,
    AmplitudeConfig
)
```

## 🎯 Common Patterns

### Pattern 1: Streamlit Page Tracking

```python
from seed_vault.ui.app_pages.helpers.telemetry import track_page_view

def my_page():
    # Track page view (automatic deduplication on reruns)
    track_page_view("/my-page", "My Page Title")

    st.title("My Page")
    # ... rest of page code
```

### Pattern 2: Button Click Event

```python
from seed_vault.ui.app_pages.helpers.telemetry import track_event

if st.button("Start Workflow"):
    track_event("workflow_started", {
        "workflow_type": "event_based",
        "user_action": "button_click"
    })
    # ... workflow logic
```

### Pattern 3: Workflow Step Tracking

```python
def complete_step(step_num, step_name):
    track_event("workflow_step_completed", {
        "step": step_num,
        "step_name": step_name,
        "workflow_type": st.session_state.workflow_type
    })
```

### Pattern 4: Settings Change

```python
def save_settings(settings):
    track_event("settings_saved", {
        "analytics_enabled": settings.analytics_enabled,
        "changed_fields": ["data_dir", "credentials"]
    })
```

### Pattern 5: Check Enabled Providers

```python
telemetry = get_telemetry_client()
if telemetry:
    print(f"Enabled: {telemetry.enabled_providers}")
    # Output: ['GA4', 'Amplitude']
```

## 🔧 Configuration Options

### Option 1: From Settings (Most Common)

```python
telemetry = TelemetryManager.from_settings(settings, db_path)
# Auto-detects providers from environment variables
```

### Option 2: Explicit Config

```python
telemetry = TelemetryManager.from_configs(
    db_path="SVdata/database.sqlite",
    analytics_enabled=True,
    ga4_config=GA4Config(
        enabled=True,
        measurement_id="G-XXXXXXXXXX",
        api_secret="secret"
    ),
    amplitude_config=AmplitudeConfig(
        enabled=True,
        api_key="amplitude-key"
    )
)
```

### Option 3: Selective Providers

```python
# Only GA4
telemetry = TelemetryManager.from_configs(
    db_path=db_path,
    analytics_enabled=True,
    ga4_config=GA4Config(enabled=True, ...),
    amplitude_config=AmplitudeConfig(enabled=False)
)
```

## 📊 Provider Comparison

| Feature             | GA4                      | Amplitude                   |
| ------------------- | ------------------------ | --------------------------- |
| **SDK Required**    | No (HTTP API)            | Yes (`amplitude-analytics`) |
| **Page Views**      | Native `page_view` event | Custom "Page Viewed" event  |
| **Session ID**      | String UUID              | Numeric (hashed)            |
| **User Properties** | Via events               | Via `identify()`            |
| **Flush Required**  | No                       | Yes (on shutdown)           |
| **Real-time**       | ~seconds                 | ~seconds                    |

## 🎨 Event Types (Standard)

### Page Views

```python
track_page_view("/main-flows", "Main Flows")
track_page_view("/settings/analytics", "Analytics Settings")
```

### Workflow Events

```python
# Start
track_event("workflow_started", {
    "workflow_type": "event_based",
    "download_type": "waveform"
})

# Step complete
track_event("workflow_step_completed", {
    "step": 1,
    "step_name": "event_search",
    "workflow_type": "event_based"
})

# Navigation
track_event("workflow_navigation", {
    "action": "back",
    "from_stage": "station_search",
    "to_stage": "event_search"
})

# Complete
track_event("workflow_completed", {
    "success": True,
    "workflow_type": "event_based",
    "total_steps": 3
})
```

### Settings Events

```python
track_event("analytics_preference_changed", {
    "new_value": True,
    "previous_value": False
})

track_event("settings_saved", {
    "analytics_enabled": True
})
```

## 🛡️ Error Handling

### Telemetry Never Breaks Your App

```python
# Safe - does nothing if disabled/misconfigured
telemetry.track_page_view("/page", "Title")
telemetry.track_event("event", {})

# Check status
if telemetry.is_enabled:
    print("Telemetry is working")
else:
    print("Telemetry disabled or misconfigured")
```

### Debug Mode

```bash
export DEBUG_TELEMETRY=1
streamlit run app.py
```

Output:

```
[TelemetryManager] Enabled providers: GA4, Amplitude
[GA4] Event sent: page_view
[Amplitude] Event sent: Page Viewed
```

## 🔍 Verification

### Check Client ID (Persistent)

```python
client_id = telemetry.get_client_id()
print(f"Client ID: {client_id}")
# Same across app restarts
```

### Check Session ID (Per-Run)

```python
session_id = telemetry.get_session_id()
print(f"Session ID: {session_id}")
# Different each run
```

### List Enabled Providers

```python
print(telemetry.enabled_providers)
# ['GA4', 'Amplitude'] or ['GA4'] or []
```

## 🚦 Best Practices

### ✅ Do

- Use `track_page_view()` helper in Streamlit (has deduplication)
- Track meaningful user actions (button clicks, workflow steps)
- Use descriptive event names and parameter keys
- Enable `DEBUG_TELEMETRY` during development
- Call `telemetry.flush()` before app shutdown

### ❌ Don't

- Track PII (names, emails, IP addresses)
- Track sensitive data (passwords, API keys, file contents)
- Track on every Streamlit rerun (use deduplication)
- Block app functionality on telemetry failures
- Commit API keys to version control

## 📁 Files Reference

```
seed_vault/analytics/
├── base_telemetry.py         # Base classes, configs
├── ga4_provider.py           # GA4 implementation
├── amplitude_provider.py     # Amplitude implementation
├── telemetry_manager.py      # Multi-provider manager
└── telemetry.py              # Legacy (backward compat)

seed_vault/ui/app_pages/helpers/
└── telemetry.py              # Streamlit helpers

Documentation:
├── TELEMETRY_ARCHITECTURE.md        # Complete architecture
├── TELEMETRY_MIGRATION_GUIDE.md     # Migration guide
├── TELEMETRY_IMPLEMENTATION.md      # Original GA4 docs
└── examples/
    └── telemetry_multi_provider_example.py  # Examples
```

## 🆘 Troubleshooting

| Issue                   | Solution                                           |
| ----------------------- | -------------------------------------------------- |
| No providers enabled    | Check `.env` has correct API keys                  |
| Import error: amplitude | Run `poetry add amplitude-analytics`               |
| Duplicate events        | Use `track_page_view()` helper (has deduplication) |
| Events not in Amplitude | Call `telemetry.flush()` before exit               |
| "Client ID is None"     | Check `analytics_enabled=True` in settings         |

## 📚 Learn More

- `TELEMETRY_ARCHITECTURE.md` - Deep dive into architecture
- `TELEMETRY_MIGRATION_GUIDE.md` - Migration from legacy system
- `examples/telemetry_multi_provider_example.py` - Working code examples
