# My Honeywell

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/github/license/TSJim/my-honeywell-ha)](LICENSE)

A custom Home Assistant integration for Honeywell Total Connect Comfort thermostats that **actually stays connected**.

## The Problem

The official Honeywell integration fails almost daily. Your thermostat goes "unavailable" and doesn't recover until you manually reload the integration. This happens because:

- Honeywell's servers return 500/502/503 errors frequently
- Session cookies expire unpredictably (401/403 errors)
- The official integration gives up on the first error

## The Solution

This integration includes a forked `aiosomecomfort` library with robust error handling:

| Issue | How It's Handled |
|-------|------------------|
| Session expired (401/403) | Automatic re-authentication |
| Server errors (500/502/503) | Exponential backoff retry |
| Transient failures | Returns cached data, only fails after 5 consecutive errors |
| Set operation fails | Retries up to 3 times |

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/TSJim/my-honeywell-ha` as an **Integration**
4. Search for "My Honeywell" and install it
5. Restart Home Assistant
6. Go to **Settings** → **Devices & Services** → **Add Integration** → **My Honeywell**

### Manual

1. Download this repository
2. Copy `custom_components/my_honeywell` to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant
4. Add the integration via **Settings** → **Devices & Services**

## Configuration

Enter your [mytotalconnectcomfort.com](https://mytotalconnectcomfort.com) credentials when prompted. You can optionally configure away temperatures for heat and cool modes.

## Migrating from Official Integration

1. Remove the official Honeywell integration from **Settings** → **Devices & Services**
2. Restart Home Assistant
3. Install this integration
4. Re-add your thermostats

Your existing automations should continue to work with the same entity IDs.

## Troubleshooting

### Enable Debug Logging

Add to `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.my_honeywell: debug
    somecomfort: debug
```

### Common Issues

| Error | Cause | Solution |
|-------|-------|----------|
| Rate limited | Too many API calls | Wait 10 minutes; integration will auto-retry |
| Cannot connect | Honeywell server issues | Integration retries automatically |
| Invalid authentication | Wrong credentials | Verify login at mytotalconnectcomfort.com |

## Supported Devices

This integration works with US Honeywell Total Connect Comfort thermostats (the ones that use mytotalconnectcomfort.com). European models using evohome are **not** supported.

## Credits

- Official HA integration: [home-assistant/core](https://github.com/home-assistant/core/tree/dev/homeassistant/components/honeywell)
- Original library: [mkmer/AIOSomecomfort](https://github.com/mkmer/AIOSomecomfort)

## License

- Integration code: Apache 2.0
- Included `aiosomecomfort` library: GPL-3.0
