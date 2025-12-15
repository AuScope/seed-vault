# Telemetry Architecture

## Overview

The Seed Vault telemetry system provides a flexible, multi-provider analytics infrastructure that supports multiple analytics services (Google Analytics 4, Amplitude, etc.) simultaneously through a unified interface.

## Architecture Principles

### 1. **Provider Pattern**

- Abstract base class defines common interface
- Each analytics service implements its own provider
- Providers are independent and can fail gracefully
- New providers can be added without modifying existing code

### 2. **Shared Context**

- Single `client_id` (persistent, SQLite-backed UUID)
- Single `session_id` per app run
- Consistent runtime detection (Streamlit vs CLI)
- Context shared across all providers

### 3. **Graceful Degradation**

- Analytics failures never break the app
- Missing SDK dependencies are handled gracefully
- Invalid configurations are detected early
- Debug mode available via `DEBUG_TELEMETRY` env var

### 4. **Privacy by Design**

- No PII (Personally Identifiable Information) tracked
- Only anonymous usage patterns
- User can disable analytics completely
- Respects analytics_enabled setting

## Core Components

### 1. Base Layer (`base_telemetry.py`)

#### `BaseTelemetryProvider` (Abstract)

Abstract base class that all providers must extend.

**Required Methods:**

- `track_page_view(page_path, page_title)` - Track virtual page navigation
- `track_event(event_name, params)` - Track custom events
- `_send_to_provider(payload)` - Send data to analytics API

**Provided Features:**

- `enrich_params()` - Adds session_id, runtime, lib_version
- `is_enabled` property - Check if provider is configured
- `get_client_id()` / `get_session_id()` - Access context

#### `TelemetryContext`

Manages shared state across all providers:

- **client_id**: Persistent UUID stored in SQLite
- **session_id**: Per-run UUID (not persisted)
- **runtime**: "streamlit" or "cli"
- **Database**: SQLite `analytics_metadata` table

#### Provider Configs

- `ProviderConfig` - Base configuration class
- `GA4Config` - Google Analytics 4 config (measurement_id, api_secret)
- `AmplitudeConfig` - Amplitude config (api_key)

Each config has an `is_valid()` method to check configuration.

### 2. Provider Implementations

#### `GA4TelemetryProvider` (`ga4_provider.py`)

Google Analytics 4 via Measurement Protocol API.

**Features:**

- HTTP-based (no SDK required)
- Virtual page URLs for single-page app tracking
- Custom events with parameter enrichment
- 2-second timeout for non-blocking

**API Endpoint:**

```
POST https://www.google-analytics.com/mp/collect
  ?measurement_id={GA_MEASUREMENT_ID}
  &api_secret={GA_API_SECRET}
```

**Event Format:**

```json
{
  "client_id": "uuid-here",
  "events": [
    {
      "name": "page_view",
      "params": {
        "page_location": "http://localhost:8501/event-search",
        "page_title": "Event Search",
        "page_path": "/event-search",
        "session_id": "session-uuid",
        "runtime": "streamlit",
        "lib_version": "1.0.0"
      }
    }
  ]
}
```

#### `AmplitudeTelemetryProvider` (`amplitude_provider.py`)

Amplitude via Python SDK (`amplitude-analytics`).

**Features:**

- SDK-based (requires `amplitude-analytics` package)
- Page views tracked as "Page Viewed" custom events
- User properties for runtime context
- Numeric session_id (Amplitude requirement)
- `flush()` method for app shutdown

**SDK Methods:**

- `amplitude.track()` - Send events
- `amplitude.identify()` - Set user properties
- `amplitude.flush()` - Force send pending events

**Event Format:**

```python
BaseEvent(
    event_type="Page Viewed",
    user_id="uuid-here",
    session_id=123456789,  # Numeric hash of session UUID
    event_properties={
        "page_path": "/event-search",
        "page_title": "Event Search",
        "session_id": "session-uuid",  # Also in properties
        "runtime": "streamlit",
        "lib_version": "1.0.0"
    }
)
```

### 3. Manager (`telemetry_manager.py`)

#### `TelemetryManager`

Unified interface for multiple providers.

**Initialization Methods:**

1. **`from_settings(settings, db_path)`** - From SeismoLoaderSettings

   - Reads environment variables
   - Auto-detects available providers
   - Most common usage

2. **`from_configs(db_path, analytics_enabled, ga4_config, amplitude_config)`**
   - Explicit provider configuration
   - For advanced use cases

**Key Methods:**

- `track_page_view(page_path, page_title)` - Routes to all enabled providers
- `track_event(event_name, params)` - Routes to all enabled providers
- `flush()` - Flush all providers (call on shutdown)
- `is_enabled` - Check if any provider is enabled
- `enabled_providers` - List enabled provider names

**Error Handling:**

- Each provider tracked independently
- One provider failure doesn't affect others
- Errors logged if `DEBUG_TELEMETRY=1`

### 4. Streamlit Integration (`ui/app_pages/helpers/telemetry.py`)

#### Singleton Pattern

```python
def init_telemetry_client(settings, db_path):
    """Initialize once, store in st.session_state"""
    if 'telemetry_client' not in st.session_state:
        manager = TelemetryManager.from_settings(settings, db_path)
        st.session_state.telemetry_client = manager
    return st.session_state.telemetry_client
```

#### Deduplication

```python
def track_page_view(page_path, page_title):
    """Only track when page actually changes"""
    last_tracked = st.session_state.get('_last_tracked_page')
    if last_tracked != page_path:
        telemetry = get_telemetry_client()
        if telemetry:
            telemetry.track_page_view(page_path, page_title)
            st.session_state._last_tracked_page = page_path
```

This prevents duplicate tracking on Streamlit reruns (critical!).

## Configuration

### Environment Variables

Required for each provider you want to use:

**Google Analytics 4:**

```bash
GA_MEASUREMENT_ID=G-XXXXXXXXXX
GA_API_SECRET=your_api_secret_here
```

**Amplitude:**

```bash
AMPLITUDE_API_KEY=your_amplitude_api_key_here
```

**Optional:**

```bash
APP_BASE_URL=https://your-domain.com  # Default: http://localhost:8501
DEBUG_TELEMETRY=1                      # Enable debug logging
```

### Settings File

User controls analytics via `SeismoLoaderSettings`:

```python
class SeismoLoaderSettings:
    analytics_enabled: bool = True        # Master switch
    analytics_popup_dismissed: bool = False
```

## Data Flow

### Initialization

```
1. App starts → get_app_settings() called
2. TelemetryManager.from_settings() creates manager
3. TelemetryContext reads/creates client_id from SQLite
4. Each provider initialized based on env vars
5. Manager stored in st.session_state.telemetry_client
```

### Page View Tracking

```
1. Page renders → track_page_view("/page-path", "Title")
2. Check _last_tracked_page in session_state
3. If different → route to all enabled providers
4. Each provider transforms to its format
5. Async HTTP POST to provider APIs
6. Update _last_tracked_page
```

### Event Tracking

```
1. User action → track_event("event_name", {params})
2. Manager routes to all enabled providers
3. Each provider enriches with session_id, runtime, lib_version
4. Each provider sends to its API
5. Failures logged but don't propagate
```

## Usage Examples

### Basic Usage

```python
from seed_vault.analytics import TelemetryManager
from seed_vault.models.config import SeismoLoaderSettings

settings = SeismoLoaderSettings.from_cfg_file("config.cfg")
telemetry = TelemetryManager.from_settings(settings, "SVdata/database.sqlite")

# Track page view
telemetry.track_page_view("/event-search", "Event Search")

# Track custom event
telemetry.track_event("workflow_started", {
    "workflow_type": "event_based",
    "download_type": "waveform"
})

# Check status
print(f"Enabled providers: {telemetry.enabled_providers}")
print(f"Client ID: {telemetry.get_client_id()}")
```

### Streamlit Integration

```python
from seed_vault.ui.app_pages.helpers.telemetry import (
    init_telemetry_client,
    track_page_view,
    track_event
)

# Initialize once (usually in get_app_settings())
telemetry = init_telemetry_client(settings, db_path)

# Track page view (with deduplication)
track_page_view("/event-search", "Event Search")

# Track custom event
track_event("button_clicked", {"button": "start_workflow"})
```

### Custom Provider Configuration

```python
from seed_vault.analytics import TelemetryManager, GA4Config, AmplitudeConfig

# Explicit configuration
manager = TelemetryManager.from_configs(
    db_path="SVdata/database.sqlite",
    analytics_enabled=True,
    ga4_config=GA4Config(
        enabled=True,
        measurement_id="G-XXXXXXXXXX",
        api_secret="secret"
    ),
    amplitude_config=AmplitudeConfig(
        enabled=True,
        api_key="your-api-key"
    )
)
```

### Adding a New Provider

1. **Create provider class** (e.g., `mixpanel_provider.py`):

```python
from .base_telemetry import BaseTelemetryProvider, ProviderConfig

@dataclass
class MixpanelConfig(ProviderConfig):
    project_token: str

    def __post_init__(self):
        self.provider_name = "Mixpanel"

    def is_valid(self) -> bool:
        return self.enabled and self.project_token is not None

class MixpanelTelemetryProvider(BaseTelemetryProvider):
    def track_page_view(self, page_path, page_title):
        # Mixpanel-specific implementation
        pass

    def track_event(self, event_name, params):
        # Mixpanel-specific implementation
        pass

    def _send_to_provider(self, payload):
        # Mixpanel API call
        pass
```

2. **Update `telemetry_manager.py`**:

```python
from .mixpanel_provider import MixpanelTelemetryProvider, MixpanelConfig

# Add to from_settings():
mixpanel_config = MixpanelConfig(
    enabled=analytics_enabled,
    project_token=os.getenv("MIXPANEL_PROJECT_TOKEN")
)
if mixpanel_config.is_valid():
    providers.append(MixpanelTelemetryProvider(...))
```

3. **Update `__init__.py`** to export new classes

4. **Update `.env.example`** with new env var

## Backward Compatibility

The old `TelemetryClient` class is preserved in `telemetry.py` and works as before. However, it only supports GA4.

New code should use `TelemetryManager` which supports multiple providers.

**Migration:**

```python
# Old (still works)
from seed_vault.analytics import TelemetryClient
telemetry = TelemetryClient(settings, db_path)

# New (recommended)
from seed_vault.analytics import TelemetryManager
telemetry = TelemetryManager.from_settings(settings, db_path)
```

The `TelemetryClient` name is aliased to `TelemetryManager` in `__init__.py` for compatibility.

## Testing

### Debug Mode

```bash
export DEBUG_TELEMETRY=1
streamlit run app.py
```

Output shows:

- Provider initialization
- Event tracking
- API responses
- Errors (if any)

### Check Enabled Providers

```python
telemetry = get_telemetry_client()
print(f"Enabled: {telemetry.enabled_providers}")
# Output: ['GA4', 'Amplitude']
```

### Verify Client ID Persistence

```python
# Run 1
telemetry = TelemetryManager.from_settings(settings, "test.db")
client_id_1 = telemetry.get_client_id()

# Run 2 (same database)
telemetry = TelemetryManager.from_settings(settings, "test.db")
client_id_2 = telemetry.get_client_id()

assert client_id_1 == client_id_2  # Should be same
```

## Performance Considerations

1. **Non-blocking**: All API calls have 2-second timeout
2. **Deduplication**: Prevents excessive API calls on Streamlit reruns
3. **Lazy initialization**: Providers only initialized if configured
4. **Graceful failure**: Analytics never blocks app functionality

## Security

1. **API keys in environment**: Never commit to version control
2. **Client ID only**: No user PII tracked
3. **Anonymous tracking**: Can't identify individual users
4. **User control**: Respects analytics_enabled setting

## Future Enhancements

Potential improvements:

- Event batching for reduced API calls
- Offline queue with retry logic
- Custom provider registry pattern
- Configuration via settings file (not just env vars)
- Event validation/schema
- Rate limiting per provider
- Provider-specific sampling rates
