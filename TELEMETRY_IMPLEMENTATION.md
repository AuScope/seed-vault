# Telemetry Implementation Summary

This document provides a comprehensive overview of the telemetry tracking implementation in Seed Vault.

## Overview

The telemetry system tracks user interactions and page views across the Streamlit application using Google Analytics 4 (GA4) Measurement Protocol API. The system uses a persistent client ID stored in SQLite to track unique users across sessions while maintaining anonymity.

## Architecture

### Core Components

1. **TelemetryClient** (`seed_vault/analytics/telemetry.py`)

   - Manages client_id persistence in SQLite
   - Sends events to GA4 Measurement Protocol API
   - Detects runtime environment (Streamlit vs CLI)
   - Handles graceful failure (never crashes the app)

2. **Telemetry Helpers** (`seed_vault/ui/app_pages/helpers/telemetry.py`)

   - Provides Streamlit-specific convenience functions
   - Implements singleton pattern via `st.session_state`
   - Exposes `track_page_view()` and `track_event()` functions

3. **Analytics Configuration** (`seed_vault/models/config.py`)
   - `analytics_enabled`: User preference for analytics (default: True)
   - `analytics_popup_dismissed`: Whether user has seen the consent popup
   - Persisted in configuration file

## Initialization

Telemetry is initialized automatically when the app starts:

```python
# In seed_vault/ui/app_pages/helpers/common.py
def get_app_settings():
    if "settings" not in st.session_state:
        # ... load settings ...
        init_telemetry_client(db_path)  # Initialize telemetry client
    return st.session_state["settings"]
```

This ensures:

- Client ID is created/loaded on first app launch
- Telemetry client is available as a singleton throughout the session
- Database path is correctly configured

## Tracked Events

### Page Views

Virtual page paths are used to track navigation in the single-page Streamlit app:

| Virtual Path                                     | Description                                     |
| ------------------------------------------------ | ----------------------------------------------- |
| `/main-flows`                                    | Main flows landing page                         |
| `/main-flows/workflow-selection`                 | Workflow selection (Stage 0)                    |
| `/main-flows/step1-event-search`                 | Step 1: Event search (event-based workflow)     |
| `/main-flows/step1-station-search`               | Step 1: Station search (station-based workflow) |
| `/main-flows/step1-station-search-continuous`    | Step 1: Station search (continuous workflow)    |
| `/main-flows/step2-station-search`               | Step 2: Station search (event-based workflow)   |
| `/main-flows/step2-event-search`                 | Step 2: Event search (station-based workflow)   |
| `/main-flows/step2-waveform-download-continuous` | Step 2: Waveform download (continuous workflow) |
| `/main-flows/step3-waveform-download`            | Step 3: Waveform download                       |
| `/db-explorer`                                   | Database explorer page                          |
| `/run-from-parameters`                           | Run from parameters page                        |
| `/settings/data`                                 | Settings - Data tab                             |
| `/settings/credentials`                          | Settings - Credentials tab                      |
| `/settings/clients`                              | Settings - Clients tab                          |
| `/settings/analytics`                            | Settings - Analytics tab                        |
| `/settings/license`                              | Settings - License tab                          |

### Custom Events

| Event Name                     | Parameters                                            | Description                        |
| ------------------------------ | ----------------------------------------------------- | ---------------------------------- |
| `workflow_started`             | `workflow_type`, `download_type`                      | User starts a workflow             |
| `workflow_step_completed`      | `workflow_type`, `step`, `step_name`, `download_type` | User completes a workflow step     |
| `workflow_navigation`          | `action`, `from_stage`, `to_stage`                    | User navigates back in workflow    |
| `workflow_completed`           | `success`, `cancelled`, `workflow_type`               | Download completes or is cancelled |
| `analytics_preference_changed` | `new_value`, `previous_value`                         | User changes analytics setting     |
| `settings_saved`               | `analytics_enabled`                                   | User saves configuration           |

### Event Enrichment

All events are automatically enriched with:

- `client_id`: Persistent UUID identifying the user
- `session_id`: Per-session UUID
- `runtime`: "streamlit" or "cli"
- `lib_version`: Seed Vault version (from `__version__`)
- `timestamp_micros`: Event timestamp

## User Consent Flow

1. **First Launch**: Analytics popup appears on first app launch

   - User can dismiss (keeps analytics enabled)
   - User can disable analytics
   - User can click "Learn More" (navigates to Settings → Analytics tab)

2. **Settings Page**: Users can toggle analytics at any time

   - Change is tracked (if analytics was enabled before toggle)
   - Must click "Save Config" to persist preference

3. **Respect User Choice**: All tracking respects `analytics_enabled` setting
   - Events are only sent when `analytics_enabled == True`
   - Telemetry gracefully handles disabled state

## Files Modified

### Core Telemetry

- `seed_vault/analytics/telemetry.py` - Core TelemetryClient class
- `seed_vault/ui/app_pages/helpers/telemetry.py` - Streamlit helper functions
- `seed_vault/models/config.py` - Analytics configuration fields

### UI Components with Tracking

- `seed_vault/ui/app_pages/main_flows.py` - Main flows page
- `seed_vault/ui/app_pages/db_explorer.py` - Database explorer
- `seed_vault/ui/app_pages/run_from_parameters.py` - Run from parameters
- `seed_vault/ui/components/settings.py` - Settings page (all tabs)
- `seed_vault/ui/components/workflows_combined.py` - Workflow stages
- `seed_vault/ui/components/waveform.py` - Waveform download completion

### Initialization

- `seed_vault/ui/app_pages/helpers/common.py` - Telemetry initialization

### Dependencies

- `pyproject.toml` - Added python-dotenv dependency

## Environment Configuration

Create a `.env` file in the project root:

```bash
# Google Analytics 4 credentials
GA_MEASUREMENT_ID=G-XXXXXXXXXX
GA_API_SECRET=your_api_secret_here

# Optional: Base URL for virtual page tracking
APP_BASE_URL=http://localhost:8501

# Optional: Enable debug logging
DEBUG_TELEMETRY=false
```

Get credentials from:

1. Google Analytics 4 property
2. Admin → Data Streams → Choose your stream
3. Measurement Protocol API secrets

## Testing

### 1. Install Dependencies

```bash
poetry install
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your GA4 credentials
```

### 3. Test with Example

```bash
python examples/telemetry_example.py
```

### 4. Run the App

```bash
poetry run streamlit run run_app.py
```

### 5. Verify in GA4

- Use DebugView for real-time event monitoring
- Check Events reports after 24-48 hours

## Privacy & Data Collection

### What We Collect

- Application usage statistics (which features are used)
- Performance metrics (page load times)
- Workflow progression (which steps users complete)
- System information (Python version, OS type)

### What We DO NOT Collect

- Personal identifying information (names, emails, IP addresses)
- Seismic data or research data
- Station codes, network codes, or event information
- File paths or directory structures
- Authentication credentials

### Client ID

- Generated once per installation
- Stored in SQLite database (`analytics_metadata` table)
- UUID4 format (completely random, not derived from user data)
- Allows tracking across sessions without identifying users

### Session ID

- Generated per application run
- Not persisted (regenerated each time app starts)
- Used to group events within a single session

## Analytics Popup

The analytics consent popup appears on first launch:

- Located in `seed_vault/ui/components/analytics_popup.py`
- Shows once per installation
- Provides three actions:
  1. **Got it!** - Dismisses popup, keeps analytics enabled
  2. **Disable Analytics** - Disables analytics and dismisses popup
  3. **Learn More** - Opens Settings page with Analytics tab selected

## Troubleshooting

### Events Not Appearing in GA4

1. Check `.env` file has correct credentials
2. Verify `analytics_enabled = True` in settings
3. Use GA4 DebugView for real-time monitoring
4. Wait 24-48 hours for data processing

### Client ID Not Persisting

1. Check database file exists and is writable
2. Verify `analytics_metadata` table created correctly
3. Check SQLite file permissions

### Import Errors

```bash
# Reinstall dependencies
poetry install

# Verify python-dotenv installed
poetry show python-dotenv
```

## Future Enhancements

Potential additions:

- Track error events with anonymized error messages
- Performance timing events (download duration, processing time)
- Feature usage heatmaps
- A/B testing support
- Export analytics data to CSV for offline analysis
- Custom dashboards in Streamlit app

## Technical Notes

### Why SQLite for Client ID?

- Lightweight (no external dependencies)
- Persistent across app restarts
- Already used for seismic data
- Simple key-value storage for metadata

### Why Virtual Page Paths?

- Streamlit is a single-page application
- GA4 expects traditional page URLs
- Virtual paths create logical "pages" for each view
- Enables funnel analysis and user flow visualization

### Why Measurement Protocol vs gtag.js?

- Streamlit runs server-side Python
- Measurement Protocol works from backend
- No JavaScript injection needed
- Full control over data collection

### Error Handling Philosophy

- Telemetry failures should NEVER crash the app
- All tracking wrapped in try/except
- Errors logged but suppressed
- App functionality takes precedence over analytics

## References

- [GA4 Measurement Protocol](https://developers.google.com/analytics/devguides/collection/protocol/ga4)
- [Streamlit Documentation](https://docs.streamlit.io/)
- [ObsPy Documentation](https://docs.obspy.org/)
- [Seed Vault Documentation](https://seed-vault.readthedocs.io/)
