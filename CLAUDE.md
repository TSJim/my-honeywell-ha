# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Custom Home Assistant integration for Honeywell Total Connect Comfort (TCC) thermostats. This is a fork of the official integration with improved error handling to prevent the daily "unavailable" failures.

## Architecture

### Two-Layer Retry Pattern

The integration implements retry logic at two levels:

1. **HTTP Layer** (`aiosomecomfort/__init__.py`): `_request_json_with_retry()` handles 401/403 (re-authenticate) and 500/502/503 (exponential backoff)

2. **Coordinator Layer** (`__init__.py`): `MyHoneywellCoordinator._async_update_data()` tracks consecutive errors and returns stale data instead of marking devices unavailable immediately (fails only after 5 consecutive errors)

3. **Entity Layer** (`climate.py`): All set operations retry 3 times with exponential backoff

### Key Components

- `aiosomecomfort/`: Forked API client library (GPL-3.0). The `AIOSomeComfort` class wraps all HTTP requests with retry logic.
- `__init__.py`: Integration setup and `MyHoneywellCoordinator` (polls every 30s)
- `climate.py`: Climate entity using `CoordinatorEntity` pattern
- `sensor.py`: Temperature/humidity sensors

### Session Cookie Handling

Honeywell's `.ASPXAUTH_TRUEHOME` cookie has malformed expiration. The code clears the `expires` attribute after each response to prevent cookie parsing errors.

## Testing

No automated tests exist. Manual testing in Home Assistant:

```bash
# Copy to HA custom_components
cp -r my_honeywell /path/to/config/custom_components/

# Enable debug logging in configuration.yaml:
# logger:
#   logs:
#     custom_components.my_honeywell: debug
#     somecomfort: debug
```

## Honeywell API

Base URL: `https://mytotalconnectcomfort.com`

| Endpoint | Purpose |
|----------|---------|
| `/portal` | Login (POST) |
| `/portal/Location/GetLocationListData/` | List locations |
| `/portal/Device/CheckDataSession/{id}` | Get device state |
| `/portal/Device/SubmitControlScreenChanges` | Set thermostat |

Rate limit: ~12 requests/hour per device. Default 30s polling is safe for 1-2 thermostats.

## Upstream Sources

- Official HA integration: `home-assistant/core/homeassistant/components/honeywell`
- Original library: `mkmer/AIOSomecomfort`

## Licensing

- HA integration code: Apache 2.0
- aiosomecomfort library: GPL-3.0
