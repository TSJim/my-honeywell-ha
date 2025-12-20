"""Climate platform for My Honeywell integration."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.climate import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    FAN_AUTO,
    FAN_DIFFUSE,
    FAN_ON,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .aiosomecomfort import SomeComfortError, APIError

_LOGGER = logging.getLogger(__name__)

# Mapping from Honeywell modes to HA modes
HVAC_MODE_MAP = {
    "heat": HVACMode.HEAT,
    "cool": HVACMode.COOL,
    "auto": HVACMode.HEAT_COOL,
    "off": HVACMode.OFF,
    "emheat": HVACMode.HEAT,  # Emergency heat
}

# Reverse mapping
HA_MODE_TO_HONEYWELL = {
    HVACMode.HEAT: "heat",
    HVACMode.COOL: "cool",
    HVACMode.HEAT_COOL: "auto",
    HVACMode.OFF: "off",
}

FAN_MODE_MAP = {
    "auto": FAN_AUTO,
    "on": FAN_ON,
    "circulate": FAN_DIFFUSE,
}

HVAC_ACTION_MAP = {
    "off": HVACAction.IDLE,
    "fan": HVACAction.FAN,
    "heat": HVACAction.HEATING,
    "cool": HVACAction.COOLING,
}

RETRY_ATTEMPTS = 3


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up climate entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    devices = data["devices"]
    cool_away_temp = data["cool_away_temp"]
    heat_away_temp = data["heat_away_temp"]

    entities = []
    for device in devices:
        entities.append(
            MyHoneywellClimate(
                coordinator,
                device,
                cool_away_temp,
                heat_away_temp,
            )
        )

    async_add_entities(entities)


class MyHoneywellClimate(CoordinatorEntity, ClimateEntity):
    """Representation of a Honeywell thermostat."""

    _attr_has_entity_name = True
    _attr_name = None
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        coordinator,
        device,
        cool_away_temp: int,
        heat_away_temp: int,
    ) -> None:
        """Initialize the thermostat."""
        super().__init__(coordinator)
        self._device = device
        self._cool_away_temp = cool_away_temp
        self._heat_away_temp = heat_away_temp
        
        self._attr_unique_id = f"{device.deviceid}_climate"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device.deviceid)},
            "name": device.name,
            "manufacturer": "Honeywell",
            "model": "Total Connect Comfort",
        }

        # Build supported features
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        
        # Add dual setpoint support for auto mode
        if self._supports_auto:
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE

        # Add fan support if available
        if device._data.get("hasFan"):
            self._attr_supported_features |= ClimateEntityFeature.FAN_MODE

    @property
    def _supports_auto(self) -> bool:
        """Check if device supports auto mode."""
        try:
            return self._device._data.get("uiData", {}).get("SwitchAutoAllowed", False)
        except (KeyError, TypeError):
            return False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self.coordinator.data:
            device_data = self.coordinator.data.get(self._device.deviceid, {})
            return device_data.get("available", False)
        return False

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement."""
        unit = self._device.temperature_unit
        if unit == "F":
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._device.current_temperature

    @property
    def current_humidity(self) -> int | None:
        """Return the current humidity."""
        return self._device.current_humidity

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        mode = self._device.system_mode
        return HVAC_MODE_MAP.get(mode, HVACMode.OFF)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return available HVAC modes."""
        modes = [HVACMode.OFF]
        
        ui_data = self._device._data.get("uiData", {})
        if ui_data.get("SwitchHeatAllowed"):
            modes.append(HVACMode.HEAT)
        if ui_data.get("SwitchCoolAllowed"):
            modes.append(HVACMode.COOL)
        if ui_data.get("SwitchAutoAllowed"):
            modes.append(HVACMode.HEAT_COOL)
            
        return modes

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return current HVAC action."""
        status = self._device.equipment_output_status
        return HVAC_ACTION_MAP.get(status, HVACAction.IDLE)

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        mode = self.hvac_mode
        if mode == HVACMode.COOL:
            return self._device.setpoint_cool
        elif mode in (HVACMode.HEAT, HVACMode.HEAT_COOL):
            return self._device.setpoint_heat
        return None

    @property
    def target_temperature_high(self) -> float | None:
        """Return the high target temperature (for auto mode)."""
        if self.hvac_mode == HVACMode.HEAT_COOL:
            return self._device.setpoint_cool
        return None

    @property
    def target_temperature_low(self) -> float | None:
        """Return the low target temperature (for auto mode)."""
        if self.hvac_mode == HVACMode.HEAT_COOL:
            return self._device.setpoint_heat
        return None

    @property
    def fan_mode(self) -> str | None:
        """Return current fan mode."""
        mode = self._device.fan_mode
        return FAN_MODE_MAP.get(mode)

    @property
    def fan_modes(self) -> list[str]:
        """Return available fan modes."""
        modes = []
        fan_data = self._device._data.get("fanData", {})
        if fan_data.get("fanModeAutoAllowed"):
            modes.append(FAN_AUTO)
        if fan_data.get("fanModeOnAllowed"):
            modes.append(FAN_ON)
        if fan_data.get("fanModeCirculateAllowed"):
            modes.append(FAN_DIFFUSE)
        return modes

    @property
    def min_temp(self) -> float:
        """Return minimum temperature."""
        ui_data = self._device._data.get("uiData", {})
        if self.hvac_mode == HVACMode.COOL:
            return ui_data.get("CoolLowerSetptLimit", 50)
        return ui_data.get("HeatLowerSetptLimit", 50)

    @property
    def max_temp(self) -> float:
        """Return maximum temperature."""
        ui_data = self._device._data.get("uiData", {})
        if self.hvac_mode == HVACMode.COOL:
            return ui_data.get("CoolUpperSetptLimit", 90)
        return ui_data.get("HeatUpperSetptLimit", 90)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature(s)."""
        for attempt in range(RETRY_ATTEMPTS):
            try:
                if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
                    if self.hvac_mode == HVACMode.COOL:
                        await self._device.set_setpoint_cool(temp)
                    else:
                        await self._device.set_setpoint_heat(temp)
                
                if (temp_low := kwargs.get(ATTR_TARGET_TEMP_LOW)) is not None:
                    await self._device.set_setpoint_heat(temp_low)
                
                if (temp_high := kwargs.get(ATTR_TARGET_TEMP_HIGH)) is not None:
                    await self._device.set_setpoint_cool(temp_high)

                await self.coordinator.async_request_refresh()
                return
                
            except SomeComfortError as ex:
                _LOGGER.warning(
                    "Failed to set temperature (attempt %d/%d): %s",
                    attempt + 1, RETRY_ATTEMPTS, ex
                )
                if attempt < RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    _LOGGER.error("Failed to set temperature after %d attempts", RETRY_ATTEMPTS)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode."""
        honeywell_mode = HA_MODE_TO_HONEYWELL.get(hvac_mode)
        if not honeywell_mode:
            _LOGGER.error("Unsupported HVAC mode: %s", hvac_mode)
            return

        for attempt in range(RETRY_ATTEMPTS):
            try:
                await self._device.set_system_mode(honeywell_mode)
                await self.coordinator.async_request_refresh()
                return
            except SomeComfortError as ex:
                _LOGGER.warning(
                    "Failed to set HVAC mode (attempt %d/%d): %s",
                    attempt + 1, RETRY_ATTEMPTS, ex
                )
                if attempt < RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    _LOGGER.error("Failed to set HVAC mode after %d attempts", RETRY_ATTEMPTS)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new fan mode."""
        # Reverse lookup
        honeywell_fan = None
        for hw_mode, ha_mode in FAN_MODE_MAP.items():
            if ha_mode == fan_mode:
                honeywell_fan = hw_mode
                break

        if not honeywell_fan:
            _LOGGER.error("Unsupported fan mode: %s", fan_mode)
            return

        for attempt in range(RETRY_ATTEMPTS):
            try:
                await self._device.set_fan_mode(honeywell_fan)
                await self.coordinator.async_request_refresh()
                return
            except SomeComfortError as ex:
                _LOGGER.warning(
                    "Failed to set fan mode (attempt %d/%d): %s",
                    attempt + 1, RETRY_ATTEMPTS, ex
                )
                if attempt < RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    _LOGGER.error("Failed to set fan mode after %d attempts", RETRY_ATTEMPTS)

    async def async_turn_on(self) -> None:
        """Turn on the thermostat."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn off the thermostat."""
        await self.async_set_hvac_mode(HVACMode.OFF)
