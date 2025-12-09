# Telemetry Setup Guide

## Quick Start

### 1. Install Dependencies

```bash
poetry install
```

This will install the new `python-dotenv` dependency.

### 2. Set Up Environment Variables

```bash
# Copy the example file
cp .env.example .env

# Edit with your GA4 credentials
nano .env  # or use your preferred editor
```

### 3. Get GA4 Credentials

1. Go to [Google Analytics](https://analytics.google.com/)
2. Click **Admin** (gear icon in bottom left)
3. Under **Property**, click **Data Streams**
4. Select your web stream (or create a new one)
5. Copy the **Measurement ID** (format: `G-XXXXXXXXXX`)
6. Scroll down to **Measurement Protocol API secrets**
7. Click **Create** to generate an API secret
8. Copy the secret value

### 4. Configure .env File

```env
GA_MEASUREMENT_ID=G-XXXXXXXXXX
GA_API_SECRET=your_api_secret_here_from_step_3
```

### 5. Verify Setup

Run the example:

```bash
python examples/telemetry_example.py
```

You should see:

```
✅ Telemetry is enabled
   Client ID: <uuid>
   Session ID: <uuid>
📊 Tracked page view: Event Search
📊 Tracked event: flow_started
```

### 6. Test in Streamlit

```bash
seed-vault
```

Navigate through the app. Events should appear in GA4 within 24-48 hours (use DebugView for real-time testing).

## Debugging

Enable debug output to see telemetry activity:

```bash
export DEBUG_TELEMETRY=1
seed-vault
```

or in `.env`:

```env
DEBUG_TELEMETRY=1
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                 Seed Vault App                      │
│  (Streamlit UI / CLI)                              │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│            TelemetryClient                          │
│  - Loads .env (GA credentials)                     │
│  - Gets/creates persistent client_id               │
│  - Generates session_id                            │
│  - Detects runtime (streamlit/cli)                 │
└────────────────────┬────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
┌──────────────┐          ┌──────────────┐
│   SQLite DB  │          │  GA4 API     │
│              │          │              │
│  Stores:     │          │  Receives:   │
│  - client_id │          │  - page_view │
│              │          │  - events    │
└──────────────┘          └──────────────┘
```

## File Structure

```
seed_vault/
├── analytics/
│   ├── __init__.py           # Module exports
│   ├── telemetry.py          # TelemetryClient implementation
│   └── README.md             # Detailed docs
├── models/
│   └── config.py             # analytics_enabled setting
└── ...

examples/
└── telemetry_example.py      # Usage examples

.env.example                  # Template for credentials
.env                          # Your credentials (gitignored)
```

## Next Steps

Once telemetry is working:

1. **Integrate into workflows** - Add tracking to main user flows
2. **Track key metrics** - Downloads, searches, errors
3. **Monitor GA4 dashboard** - Review usage patterns
4. **Iterate** - Add more events based on insights

## Troubleshooting

**Problem: "Telemetry is disabled"**

- Check `.env` file exists and has valid values
- Verify `analytics_enabled = True` in config.cfg
- Make sure poetry install completed successfully

**Problem: "Import dotenv could not be resolved"**

- Run `poetry install` to install dependencies
- Restart your IDE/editor

**Problem: No events in GA4**

- Wait 24-48 hours for data processing
- Use GA4 DebugView for real-time testing
- Check API secret is correct
- Enable DEBUG_TELEMETRY to see if events are sending

**Problem: Database errors**

- Ensure db_path directory exists and is writable
- Check SQLite database isn't corrupted
- Database will auto-create if missing

## Support

For questions or issues:

- See `seed_vault/analytics/README.md` for detailed API docs
- Check `examples/telemetry_example.py` for usage patterns
- Open an issue on GitHub
