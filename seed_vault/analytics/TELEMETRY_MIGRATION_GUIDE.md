# Telemetry Migration Guide

## Migrating from Legacy TelemetryClient to TelemetryManager

### Overview

The new telemetry system introduces a multi-provider architecture that supports GA4, Amplitude, and future analytics services simultaneously. The migration is **backward compatible** - existing code will continue to work unchanged.

### What's New?

- **Multi-provider support**: Send events to GA4 and Amplitude at the same time
- **Provider abstraction**: Easy to add new analytics services
- **Shared context**: Single client_id/session_id across all providers
- **Better error handling**: Provider failures don't affect each other

### Do You Need to Migrate?

**No, not immediately.** The old `TelemetryClient` is aliased to `TelemetryManager` for backward compatibility. However, migrating gives you:

- Access to multiple analytics providers
- Better maintainability
- Future-proof architecture

## Migration Scenarios

### Scenario 1: Basic Usage (No Changes Needed)

**Before:**

```python
from seed_vault.analytics import TelemetryClient

telemetry = TelemetryClient(settings, db_path="SVdata/database.sqlite")
telemetry.track_page_view("/page", "Page Title")
telemetry.track_event("event_name", {"param": "value"})
```

**After (unchanged - still works):**

```python
from seed_vault.analytics import TelemetryClient

telemetry = TelemetryClient(settings, db_path="SVdata/database.sqlite")
telemetry.track_page_view("/page", "Page Title")
telemetry.track_event("event_name", {"param": "value"})
```

`TelemetryClient` is now an alias for `TelemetryManager`, so existing code works identically.

### Scenario 2: Using New TelemetryManager (Recommended)

**Before:**

```python
from seed_vault.analytics import TelemetryClient

telemetry = TelemetryClient(settings, db_path="SVdata/database.sqlite")
```

**After:**

```python
from seed_vault.analytics import TelemetryManager

telemetry = TelemetryManager.from_settings(settings, db_path="SVdata/database.sqlite")
```

Benefits:

- More explicit about multi-provider support
- Access to `enabled_providers` property
- Future-proof naming

### Scenario 3: Streamlit Helpers (No Changes)

**Before:**

```python
from seed_vault.ui.app_pages.helpers.telemetry import (
    init_telemetry_client,
    track_page_view,
    track_event
)

telemetry = init_telemetry_client(settings, db_path)
track_page_view("/page", "Title")
track_event("event_name", {})
```

**After (unchanged - still works):**

```python
from seed_vault.ui.app_pages.helpers.telemetry import (
    init_telemetry_client,
    track_page_view,
    track_event
)

telemetry = init_telemetry_client(settings, db_path)
track_page_view("/page", "Title")
track_event("event_name", {})
```

The helper functions automatically use the new `TelemetryManager` internally.

## Enabling Multiple Providers

### Step 1: Add Amplitude to Environment

**Before (.env):**

```bash
GA_MEASUREMENT_ID=G-XXXXXXXXXX
GA_API_SECRET=your_ga4_secret
```

**After (.env):**

```bash
# Google Analytics 4
GA_MEASUREMENT_ID=G-XXXXXXXXXX
GA_API_SECRET=your_ga4_secret

# Amplitude
AMPLITUDE_API_KEY=your_amplitude_key
```

### Step 2: No Code Changes Required!

The `TelemetryManager` automatically detects and enables providers based on environment variables. If both GA4 and Amplitude credentials are present, both will be used.

### Step 3: Verify Providers (Optional)

```python
telemetry = TelemetryManager.from_settings(settings, db_path)
print(f"Enabled providers: {telemetry.enabled_providers}")
# Output: ['GA4', 'Amplitude']
```

## Advanced: Using Specific Providers

If you need fine-grained control:

```python
from seed_vault.analytics import TelemetryManager, GA4Config, AmplitudeConfig

# Only enable GA4
telemetry = TelemetryManager.from_configs(
    db_path="SVdata/database.sqlite",
    analytics_enabled=True,
    ga4_config=GA4Config(
        enabled=True,
        measurement_id="G-XXXXXXXXXX",
        api_secret="secret"
    ),
    amplitude_config=AmplitudeConfig(enabled=False)
)
```

## File Structure Changes

### Old Structure

```
seed_vault/analytics/
├── __init__.py
└── telemetry.py          # TelemetryClient (GA4 only)
```

### New Structure

```
seed_vault/analytics/
├── __init__.py           # Exports all classes
├── telemetry.py          # Legacy TelemetryClient (kept for compatibility)
├── base_telemetry.py     # Base classes and configs
├── ga4_provider.py       # GA4 implementation
├── amplitude_provider.py # Amplitude implementation
└── telemetry_manager.py  # Multi-provider manager
```

## Import Changes (Optional)

You can now import specific components:

```python
# Old way (still works)
from seed_vault.analytics import TelemetryClient

# New way (more options)
from seed_vault.analytics import (
    TelemetryManager,      # Main interface
    GA4Config,             # GA4 configuration
    AmplitudeConfig,       # Amplitude configuration
    GA4TelemetryProvider,  # Direct GA4 access
    AmplitudeTelemetryProvider,  # Direct Amplitude access
    TelemetryContext       # Shared context
)
```

## Testing Your Migration

### 1. Enable Debug Mode

```bash
export DEBUG_TELEMETRY=1
```

### 2. Run Your App

```bash
streamlit run app.py
```

### 3. Check Console Output

```
[TelemetryManager] Enabled providers: GA4, Amplitude
[GA4] Event sent: page_view
[Amplitude] Event sent: Page Viewed
```

### 4. Verify in Analytics Dashboards

- **GA4**: Check Realtime report
- **Amplitude**: Check User Activity or Events

## Common Issues

### Issue 1: "No providers enabled"

**Cause**: Missing environment variables

**Solution**: Check `.env` file has correct credentials:

```bash
GA_MEASUREMENT_ID=G-XXXXXXXXXX
GA_API_SECRET=your_secret
AMPLITUDE_API_KEY=your_key
```

### Issue 2: "ModuleNotFoundError: No module named 'amplitude'"

**Cause**: Amplitude SDK not installed

**Solution**:

```bash
poetry add amplitude-analytics
# or
pip install amplitude-analytics
```

### Issue 3: Events not appearing in Amplitude

**Cause**: Need to flush events before shutdown

**Solution**:

```python
# Before app exit
telemetry.flush()
```

### Issue 4: Duplicate events in analytics

**Cause**: Streamlit reruns triggering multiple events

**Solution**: Use the `track_page_view()` helper which has built-in deduplication:

```python
from seed_vault.ui.app_pages.helpers.telemetry import track_page_view

# This automatically prevents duplicates on reruns
track_page_view("/page", "Title")
```

## Rollback Plan

If you need to rollback, the old `telemetry.py` file is preserved. You can:

1. Update imports to use `LegacyTelemetryClient`:

```python
from seed_vault.analytics import LegacyTelemetryClient as TelemetryClient
```

2. Or temporarily modify `__init__.py` to export the legacy version

## Performance Impact

The new system has **minimal performance impact**:

- Same 2-second timeout per provider
- Providers run independently (one failure doesn't affect others)
- Deduplication prevents duplicate API calls
- No batching overhead (yet)

## Next Steps

1. ✅ Update `.env` with Amplitude API key
2. ✅ Run with `DEBUG_TELEMETRY=1` to verify
3. ✅ Check analytics dashboards for data
4. ✅ Optionally update imports to use `TelemetryManager`
5. ✅ Read `TELEMETRY_ARCHITECTURE.md` for deep dive

## Questions?

See:

- `TELEMETRY_ARCHITECTURE.md` - Complete architecture documentation
- `examples/telemetry_multi_provider_example.py` - Working examples
- `TELEMETRY_IMPLEMENTATION.md` - Original implementation guide
