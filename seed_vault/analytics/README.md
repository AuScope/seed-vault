# Analytics Module

This module provides telemetry tracking for Seed Vault with Google Analytics 4 integration.

## Features

- **SQLite-persistent client ID**: User identity is preserved across sessions
- **Session tracking**: Each process run gets a unique session ID
- **Virtual page views**: Track logical app screens on single-page Streamlit apps
- **Custom event tracking**: Track user actions, errors, and feature usage
- **Runtime detection**: Automatically detects Streamlit vs CLI execution
- **Graceful degradation**: Fails silently when disabled or misconfigured
- **Privacy-focused**: Only tracks anonymous usage data when explicitly enabled

## Setup

### 1. Install Dependencies

```bash
poetry install
```

This will install `python-dotenv` and other required packages.

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your GA4 credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
GA_MEASUREMENT_ID=G-XXXXXXXXXX
GA_API_SECRET=your_api_secret_here
```

**Where to get these values:**

1. Go to [Google Analytics](https://analytics.google.com/)
2. Navigate to **Admin** → **Data Streams**
3. Select your stream (or create one)
4. **Measurement ID**: Shown at the top (format: `G-XXXXXXXXXX`)
5. **API Secret**: Scroll down to **Measurement Protocol API secrets** → **Create**

### 3. Enable Analytics in Config

In your `config.cfg`:

```ini
[ANALYTICS]
analytics_enabled = True
analytics_popup_dismissed = False
```

## Usage

### Basic Example

```python
from seed_vault.analytics import TelemetryClient
from seed_vault.models.config import SeismoLoaderSettings

# Load settings
settings = SeismoLoaderSettings.from_cfg_file("config.cfg")

# Initialize telemetry (uses existing database for persistent client_id)
telemetry = TelemetryClient(settings, db_path="SVdata/database.sqlite")

# Track a virtual page view
telemetry.track_page_view("/event-search", "Event Search")

# Track a custom event
telemetry.track_event("flow_started", {"flow_type": "event_based"})
```

### Streamlit Integration

```python
# In your Streamlit page (e.g., main_flows.py)
from seed_vault.analytics import init_telemetry

settings = get_app_settings()
telemetry = init_telemetry(settings, "SVdata/database.sqlite")

# Track page navigation
telemetry.track_page_view("/main-flows/event-search", "Event Search")

# Track user actions
telemetry.track_event("search_submitted", {
    "min_magnitude": 5.5,
    "num_results": 10
})
```

### Virtual Page Paths

Since Streamlit apps run on a single URL, we use **virtual paths** to track different logical screens:

- `/event-search` - Event search step
- `/station-search` - Station search step
- `/waveform-download` - Waveform download step
- `/db-explorer` - Database explorer
- `/settings` - Settings page

These appear as real page views in GA4 with URLs like:

- `http://localhost:8501/event-search`
- `http://localhost:8501/station-search`

## Architecture

### Database Schema

```sql
CREATE TABLE IF NOT EXISTS analytics_metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

Stores:

- `client_id`: Persistent UUID identifying this installation

### Event Payload

All events include:

```json
{
  "client_id": "uuid-v4",
  "events": [
    {
      "name": "event_name",
      "params": {
        "session_id": "uuid-v4",
        "runtime": "streamlit|cli",
        "lib_version": "1.0.0",
        ...
      }
    }
  ]
}
```

### Runtime Detection

The client automatically detects:

- **Streamlit**: When running under Streamlit server
- **CLI**: When running as command-line tool

This is tracked in the `runtime` parameter of all events.

## Privacy & Security

### What We Track

- Anonymous usage patterns (page views, features used)
- Performance metrics (load times, errors)
- System info (runtime type, library version)

### What We DON'T Track

- Personal information (names, emails, IPs)
- Seismic data or research data
- File paths or directory structures
- Authentication credentials

### Security Best Practices

1. **Never commit `.env` file** - It's in `.gitignore`
2. **Don't log secrets** - API secrets are never printed
3. **Fail silently** - Telemetry never crashes the app
4. **User control** - Respects `analytics_enabled` setting

## Debugging

Enable debug output:

```bash
export DEBUG_TELEMETRY=1
seed-vault
```

This will print:

- Client ID generation
- Event sending confirmations
- Error messages (if any)

## Examples

See `examples/telemetry_example.py` for comprehensive usage examples:

```bash
python examples/telemetry_example.py
```

## API Reference

### `TelemetryClient`

**Constructor:**

```python
TelemetryClient(settings, db_path: str)
```

**Methods:**

- `track_page_view(page_path: str, page_title: str)` - Track virtual page view
- `track_event(name: str, params: dict)` - Track custom event
- `is_enabled` - Check if telemetry is enabled
- `get_client_id()` - Get persistent client ID
- `get_session_id()` - Get current session ID

### `init_telemetry`

Helper function:

```python
telemetry = init_telemetry(settings, db_path)
```

## Troubleshooting

**Telemetry not working?**

1. Check `.env` file exists with valid credentials
2. Verify `analytics_enabled = True` in config
3. Run with `DEBUG_TELEMETRY=1` to see error messages
4. Check database path is writable

**Events not appearing in GA4?**

1. Wait 24-48 hours for processing
2. Use GA4 DebugView for real-time testing
3. Verify Measurement ID format: `G-XXXXXXXXXX`
4. Check API secret is valid

## License

Same as Seed Vault project (CSIRO Open Source Software License).
