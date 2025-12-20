"""
My Honeywell - Improved Home Assistant Integration for Honeywell TCC Thermostats.

This is a fork of the official Honeywell integration with:
- Automatic retry on transient errors (500/502/503)
- Automatic re-authentication on session expiration (401/403)
- Better error recovery in the coordinator
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_COOL_AWAY_TEMPERATURE,
    CONF_HEAT_AWAY_TEMPERATURE,
    DEFAULT_COOL_AWAY_TEMPERATURE,
    DEFAULT_HEAT_AWAY_TEMPERATURE,
    DEFAULT_RETRY_COUNT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

# Import our improved library
from .aiosomecomfort import (
    AIOSomeComfort,
    AuthError,
    APIRateLimited,
    ConnectionError as SomeComfortConnectionError,
    ServiceUnavailable,
    SomeComfortError,
    UnauthorizedError,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up My Honeywell from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    # Get away temps from options first, then data (for backwards compat), then defaults
    cool_away_temp = entry.options.get(
        CONF_COOL_AWAY_TEMPERATURE,
        entry.data.get(CONF_COOL_AWAY_TEMPERATURE, DEFAULT_COOL_AWAY_TEMPERATURE)
    )
    heat_away_temp = entry.options.get(
        CONF_HEAT_AWAY_TEMPERATURE,
        entry.data.get(CONF_HEAT_AWAY_TEMPERATURE, DEFAULT_HEAT_AWAY_TEMPERATURE)
    )

    # Create a session that persists
    session = aiohttp.ClientSession()

    # Create our improved client
    client = AIOSomeComfort(
        username=username,
        password=password,
        session=session,
        retry_count=DEFAULT_RETRY_COUNT,
    )

    try:
        await client.login()
        await client.discover()
    except AuthError as ex:
        await session.close()
        raise ConfigEntryAuthFailed(f"Authentication failed: {ex}") from ex
    except APIRateLimited as ex:
        await session.close()
        raise ConfigEntryNotReady(f"Rate limited: {ex}") from ex
    except (SomeComfortConnectionError, ServiceUnavailable, SomeComfortError) as ex:
        await session.close()
        raise ConfigEntryNotReady(f"Connection failed: {ex}") from ex

    # Collect all devices
    devices = []
    for location in client.locations_by_id.values():
        for device in location.devices_by_id.values():
            devices.append(device)

    if not devices:
        await session.close()
        raise ConfigEntryNotReady("No devices found")

    _LOGGER.info("Found %d Honeywell device(s)", len(devices))

    # Store data in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "devices": devices,
        "cool_away_temp": cool_away_temp,
        "heat_away_temp": heat_away_temp,
        "session": session,
    }

    # Create coordinator with improved error handling
    coordinator = MyHoneywellCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id]["coordinator"] = coordinator

    # Do initial refresh
    await coordinator.async_config_entry_first_refresh()

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        # Close the session
        session = data.get("session")
        if session:
            await session.close()

    return unload_ok


class MyHoneywellCoordinator(DataUpdateCoordinator):
    """
    Improved coordinator with automatic retry and re-authentication.

    This is the KEY IMPROVEMENT - we handle errors gracefully and recover
    instead of just marking devices as unavailable.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.entry = entry
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5

    def _get_data(self):
        """Get the integration data from hass.data."""
        return self.hass.data[DOMAIN][self.entry.entry_id]

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Fetch data with robust error handling.

        This method implements:
        1. Automatic re-authentication on auth errors
        2. Graceful handling of transient errors
        3. Progressive backoff on repeated failures
        """
        integration_data = self._get_data()
        client = integration_data["client"]
        devices = integration_data["devices"]

        try:
            # Ensure we're authenticated
            await client.ensure_authenticated()

            # Refresh all devices
            device_data = {}
            for device in devices:
                try:
                    await device.refresh()
                    device_data[device.deviceid] = {
                        "device": device,
                        "available": device.is_alive,
                    }
                    _LOGGER.debug(
                        "Refreshed %s: temp=%s, mode=%s",
                        device.name,
                        device.current_temperature,
                        device.system_mode,
                    )
                except SomeComfortError as ex:
                    _LOGGER.warning("Failed to refresh %s: %s", device.name, ex)
                    device_data[device.deviceid] = {
                        "device": device,
                        "available": False,
                    }

            # Reset error counter on success
            self._consecutive_errors = 0
            return device_data

        except UnauthorizedError as ex:
            _LOGGER.warning("Session expired, attempting re-authentication: %s", ex)
            try:
                await client.login()
                # Retry the update after re-auth
                return await self._async_update_data()
            except AuthError as auth_ex:
                self._consecutive_errors += 1
                raise UpdateFailed(f"Re-authentication failed: {auth_ex}") from auth_ex

        except APIRateLimited as ex:
            self._consecutive_errors += 1
            _LOGGER.warning("Rate limited, will retry later: %s", ex)
            # Don't raise UpdateFailed for rate limiting - just skip this update
            return self.data if self.data else {}

        except ServiceUnavailable as ex:
            self._consecutive_errors += 1
            _LOGGER.warning(
                "Service unavailable (error %d/%d): %s",
                self._consecutive_errors,
                self._max_consecutive_errors,
                ex,
            )
            if self._consecutive_errors >= self._max_consecutive_errors:
                raise UpdateFailed(f"Service unavailable after {self._consecutive_errors} attempts: {ex}") from ex
            # Return stale data for transient errors
            return self.data if self.data else {}

        except SomeComfortConnectionError as ex:
            self._consecutive_errors += 1
            _LOGGER.warning(
                "Connection error (error %d/%d): %s",
                self._consecutive_errors,
                self._max_consecutive_errors,
                ex,
            )
            if self._consecutive_errors >= self._max_consecutive_errors:
                raise UpdateFailed(f"Connection error after {self._consecutive_errors} attempts: {ex}") from ex
            return self.data if self.data else {}

        except Exception as ex:
            self._consecutive_errors += 1
            _LOGGER.exception("Unexpected error during update: %s", ex)
            raise UpdateFailed(f"Unexpected error: {ex}") from ex
