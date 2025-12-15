# Telemetry Testing Checklist

This checklist helps verify that telemetry tracking is properly implemented across the Seed Vault application.

## Pre-Testing Setup

- [ ] Created `.env` file with valid GA4 credentials
  ```bash
  GA_MEASUREMENT_ID=G-XXXXXXXXXX
  GA_API_SECRET=your_api_secret_here
  APP_BASE_URL=http://localhost:8501
  DEBUG_TELEMETRY=true  # Enable for testing
  ```
- [ ] Installed dependencies: `poetry install`
- [ ] Verified python-dotenv is installed: `poetry show python-dotenv`
- [ ] Set up GA4 DebugView (Configure → DebugView in GA4)

## Core Initialization

- [ ] **Client ID Creation**: On first app launch, client_id is created in database

  - Check: `sqlite3 SVdata/database.sqlite "SELECT * FROM analytics_metadata WHERE key='client_id'"`
  - Expected: Single UUID4 value

- [ ] **Session ID Generation**: New session_id each app run

  - Check debug logs for different session_id on each launch

- [ ] **Settings Load**: Telemetry initializes when `get_app_settings()` is called
  - Check: No import errors on startup
  - Check: `st.session_state` contains telemetry client

## Analytics Consent Flow

### First Launch Popup

- [ ] Popup appears on first app launch
- [ ] **"Got it!" button**: Dismisses popup, analytics stays enabled
  - Check: `analytics_popup_dismissed = True` in settings
  - Check: `analytics_enabled = True` in settings
- [ ] **"Disable Analytics" button**: Disables analytics
  - Check: `analytics_popup_dismissed = True` in settings
  - Check: `analytics_enabled = False` in settings
  - Check: No events sent to GA4 after this
- [ ] **"Learn More" button**: Opens Settings page with Analytics tab selected
  - Check: Navigates to Settings page
  - Check: Analytics tab is pre-selected

### Settings Page Control

- [ ] Analytics toggle reflects current state
- [ ] Toggling analytics tracks `analytics_preference_changed` event
  - Event params: `new_value`, `previous_value`
- [ ] "Save Config" button saves analytics preference
  - Tracks `settings_saved` event
  - Persists to config file

## Page View Tracking

### Main Pages

- [ ] `/main-flows` - Main Flows page loads
- [ ] `/db-explorer` - Database Explorer page loads
- [ ] `/run-from-parameters` - Run from Parameters page loads

### Settings Tabs

- [ ] `/settings/data` - Data tab loads
- [ ] `/settings/credentials` - Credentials tab loads
- [ ] `/settings/clients` - Clients tab loads
- [ ] `/settings/analytics` - Analytics tab loads
- [ ] `/settings/license` - License tab loads

### Workflow Stages - Event-Based

- [ ] `/main-flows/workflow-selection` - Stage 0 (workflow selection)
- [ ] `/main-flows/step1-event-search` - Stage 1 (event search)
- [ ] `/main-flows/step2-station-search` - Stage 2 (station search)
- [ ] `/main-flows/step3-waveform-download` - Stage 3 (waveform download)

### Workflow Stages - Station-Based

- [ ] `/main-flows/workflow-selection` - Stage 0 (workflow selection)
- [ ] `/main-flows/step1-station-search` - Stage 1 (station search)
- [ ] `/main-flows/step2-event-search` - Stage 2 (event search)
- [ ] `/main-flows/step3-waveform-download` - Stage 3 (waveform download)

### Workflow Stages - Continuous

- [ ] `/main-flows/workflow-selection` - Stage 0 (workflow selection)
- [ ] `/main-flows/step1-station-search-continuous` - Stage 1 (station search)
- [ ] `/main-flows/step2-waveform-download-continuous` - Stage 2 (waveform download)

## Event Tracking

### Workflow Events

- [ ] **workflow_started**: Clicking "Start" button on workflow selection

  - Event params: `workflow_type`, `download_type`
  - Verify correct workflow type (EVENT_BASED, STATION_BASED, CONTINUOUS)

- [ ] **workflow_step_completed**: Clicking "Next" after each step

  - Event params: `workflow_type`, `step`, `step_name`, `download_type`
  - Test on Step 1 completion
  - Test on Step 2 completion

- [ ] **workflow_navigation**: Clicking "Previous" button

  - Event params: `action`, `from_stage`, `to_stage`
  - Test navigation from Stage 1 → 0
  - Test navigation from Stage 2 → 1
  - Test navigation from Stage 3 → 2

- [ ] **workflow_completed**: Download finishes or is cancelled
  - Event params: `success`, `cancelled`, `workflow_type`
  - Test successful download
  - Test cancelled download
  - Test failed download

### Settings Events

- [ ] **analytics_preference_changed**: Toggle analytics in Settings

  - Event params: `new_value`, `previous_value`
  - Test enabling analytics
  - Test disabling analytics

- [ ] **settings_saved**: Click "Save Config" button
  - Event params: `analytics_enabled`

## Event Enrichment

Verify all events include automatic parameters:

- [ ] `client_id`: Persistent UUID (same across sessions)
- [ ] `session_id`: Session UUID (different each app run)
- [ ] `runtime`: Should be "streamlit" when running in browser
- [ ] `lib_version`: Seed Vault version number
- [ ] `timestamp_micros`: Event timestamp

Check in GA4 DebugView → Event details

## Analytics Disabled State

When `analytics_enabled = False`:

- [ ] No events sent to GA4
- [ ] No errors in console
- [ ] App functions normally
- [ ] Client ID still exists in database (not deleted)
- [ ] Re-enabling analytics resumes tracking

## Error Handling

- [ ] **Invalid GA credentials**: App runs normally, no crash

  - Test with wrong `GA_MEASUREMENT_ID`
  - Test with wrong `GA_API_SECRET`
  - Check: Debug logs show error, but app continues

- [ ] **Missing .env file**: App runs normally, no crash

  - Test without `.env` file
  - Check: Telemetry disabled gracefully

- [ ] **Database write failure**: App runs normally

  - Test with read-only database (if possible)
  - Check: Client ID uses fallback or generates new one

- [ ] **Network timeout**: App doesn't hang
  - Test with network disconnected
  - Check: Events fail silently after 2-second timeout

## GA4 Verification

### DebugView (Real-time)

- [ ] Open GA4 → Configure → DebugView
- [ ] Perform actions in app
- [ ] See events appear within seconds
- [ ] Verify event parameters are correct
- [ ] Check client_id is consistent across events

### Events Report (24-48 hours)

- [ ] Open GA4 → Reports → Engagement → Events
- [ ] See custom events listed:
  - [ ] page_view
  - [ ] workflow_started
  - [ ] workflow_step_completed
  - [ ] workflow_navigation
  - [ ] workflow_completed
  - [ ] analytics_preference_changed
  - [ ] settings_saved

### User Properties

- [ ] Check that `runtime` dimension is captured
- [ ] Verify session tracking works (session_id groups events)

## Performance Testing

- [ ] App startup time not significantly impacted
- [ ] Page transitions remain smooth
- [ ] Button clicks respond immediately (tracking doesn't block UI)
- [ ] Download performance unchanged

## Privacy Verification

### Data NOT Being Sent

Verify these are NOT in GA4 events:

- [ ] User names or emails
- [ ] File paths or directory names
- [ ] Station codes, network codes, event IDs
- [ ] IP addresses (check GA4 IP anonymization setting)
- [ ] Authentication credentials
- [ ] Seismic data content

### Data Being Sent

Verify only these are in GA4:

- [ ] Page paths (virtual URLs)
- [ ] Event names (workflow_started, etc.)
- [ ] Event parameters (workflow_type, step numbers)
- [ ] Client ID (anonymous UUID)
- [ ] Session ID (anonymous UUID)
- [ ] Runtime environment (streamlit/cli)
- [ ] Library version number
- [ ] Timestamps

## CLI Mode Testing

- [ ] Run from CLI: `python examples/telemetry_example.py`
- [ ] Verify `runtime = "cli"` in events
- [ ] Check events still sent correctly
- [ ] Verify same client_id as Streamlit (if using same database)

## Multi-Session Testing

- [ ] Launch app, perform actions, close app
- [ ] Relaunch app, perform actions
- [ ] Verify same `client_id` in both sessions
- [ ] Verify different `session_id` in each session
- [ ] Check GA4 shows correct user retention

## Documentation Verification

- [ ] README.md mentions analytics
- [ ] TELEMETRY_SETUP.md has complete setup instructions
- [ ] TELEMETRY_IMPLEMENTATION.md documents architecture
- [ ] docs/telemetry_quick_reference.md helps developers
- [ ] examples/telemetry_example.py runs successfully

## Regression Testing

After implementing telemetry, verify core functionality still works:

- [ ] Event-based workflow downloads data
- [ ] Station-based workflow downloads data
- [ ] Continuous workflow downloads data
- [ ] Database explorer loads and displays data
- [ ] Settings save and load correctly
- [ ] Authentication credentials work
- [ ] SDS sync functionality works

## Sign-Off

- [ ] All page views tracked correctly
- [ ] All major user actions tracked
- [ ] Analytics consent respected
- [ ] Privacy guidelines followed
- [ ] No performance degradation
- [ ] No new bugs introduced
- [ ] Documentation complete
- [ ] Ready for production

## Notes

Use this space for testing notes, observations, or issues found:

```
Date: ___________
Tester: ___________

Issues Found:
1.
2.
3.

Observations:
-
-
-
```
