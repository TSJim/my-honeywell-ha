# My Honeywell - Improved Home Assistant Integration

A drop-in replacement for the official Honeywell Total Connect Comfort integration that **doesn't fail every day**.

## What's Different?

The official integration uses `aiosomecomfort` library which doesn't handle:
- Session expiration (401/403 errors)
- Server instability (500/502/503 errors)
- Automatic recovery

**This integration includes a forked library with:**
- ✅ Automatic re-authentication when sessions expire
- ✅ Exponential backoff retry on transient errors
- ✅ Better coordinator error handling that doesn't mark devices unavailable on temporary issues
- ✅ Consecutive error tracking - only fails after multiple attempts

## Installation

### Method 1: HACS (Recommended)
1. Add this repository to HACS as a custom repository
2. Install "My Honeywell" from HACS
3. Restart Home Assistant
4. Add the integration via Settings → Integrations

### Method 2: Manual Installation
1. Copy the `my_honeywell` folder to your `config/custom_components/` directory
2. Restart Home Assistant
3. Add the integration via Settings → Integrations

```
config/
└── custom_components/
    └── my_honeywell/
        ├── __init__.py
        ├── climate.py
        ├── sensor.py
        ├── config_flow.py
        ├── const.py
        ├── manifest.json
        ├── strings.json
        └── aiosomecomfort/
            ├── __init__.py
            ├── device.py
            ├── location.py
            └── exceptions.py
```

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "My Honeywell"
4. Enter your mytotalconnectcomfort.com credentials
5. Optionally set away temperatures

## Migration from Official Integration

1. **Remove** the official Honeywell integration
2. **Restart** Home Assistant
3. **Install** this integration
4. **Re-add** your thermostats

Your automations using `climate.your_thermostat` should continue to work.

## Troubleshooting

### Enable Debug Logging

Add to your `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.my_honeywell: debug
    somecomfort: debug
```

### Common Issues

**"Rate limited"**
- Honeywell limits API calls. Wait 10 minutes before trying again.
- The integration will automatically retry.

**"Cannot connect"**
- Honeywell's servers are often unstable.
- The integration will retry automatically up to 5 times before marking as unavailable.

**"Invalid authentication"**
- Check your credentials at mytotalconnectcomfort.com
- Your password may have changed

## Technical Details

### Error Handling Flow

```
API Call
    │
    ▼
┌─────────────────┐
│ Request Failed? │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
 401/403    500/502/503
    │         │
    ▼         ▼
Re-login   Wait (backoff)
    │         │
    └────┬────┘
         │
         ▼
    Retry (up to 3x)
         │
    ┌────┴────┐
    ▼         ▼
 Success    Fail
    │         │
    ▼         ▼
  Return   Track error count
            (fail after 5)
```

### Files Overview

| File | Purpose |
|------|---------|
| `__init__.py` | Integration setup, coordinator with improved error handling |
| `climate.py` | Climate entity with retry on set operations |
| `sensor.py` | Temperature/humidity sensors |
| `config_flow.py` | UI configuration |
| `aiosomecomfort/` | Forked library with auto-retry |

## Credits

- Original integration: [Home Assistant Core](https://github.com/home-assistant/core/tree/dev/homeassistant/components/honeywell)
- Original library: [mkmer/AIOSomecomfort](https://github.com/mkmer/AIOSomecomfort)
- Based on: [kk7ds/somecomfort](https://github.com/kk7ds/somecomfort)

## License

This integration is released under the Apache 2.0 license (same as Home Assistant).
The included `aiosomecomfort` library is GPL-3.0.
