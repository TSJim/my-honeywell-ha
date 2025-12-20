"""Sensor platform for My Honeywell integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    devices = data["devices"]

    entities = []
    for device in devices:
        # Indoor humidity sensor
        if device.current_humidity is not None:
            entities.append(
                MyHoneywellHumiditySensor(coordinator, device, "indoor")
            )
        
        # Outdoor temperature sensor
        if device.outdoor_temperature is not None:
            entities.append(
                MyHoneywellTemperatureSensor(coordinator, device, "outdoor")
            )
        
        # Outdoor humidity sensor
        if device.outdoor_humidity is not None:
            entities.append(
                MyHoneywellHumiditySensor(coordinator, device, "outdoor")
            )
    
    async_add_entities(entities)


class MyHoneywellSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Honeywell sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, device, sensor_type: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device = device
        self._sensor_type = sensor_type
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device.deviceid)},
            "name": device.name,
            "manufacturer": "Honeywell",
            "model": "Total Connect Comfort",
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self.coordinator.data:
            device_data = self.coordinator.data.get(self._device.deviceid, {})
            return device_data.get("available", False)
        return False


class MyHoneywellTemperatureSensor(MyHoneywellSensorBase):
    """Outdoor temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device, sensor_type: str) -> None:
        """Initialize the temperature sensor."""
        super().__init__(coordinator, device, sensor_type)
        self._attr_unique_id = f"{device.deviceid}_{sensor_type}_temperature"
        self._attr_name = f"{sensor_type.title()} temperature"

    @property
    def native_value(self) -> float | None:
        """Return the temperature."""
        if self._sensor_type == "outdoor":
            return self._device.outdoor_temperature
        return self._device.current_temperature

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        unit = self._device.temperature_unit
        if unit == "F":
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS


class MyHoneywellHumiditySensor(MyHoneywellSensorBase):
    """Humidity sensor."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator, device, sensor_type: str) -> None:
        """Initialize the humidity sensor."""
        super().__init__(coordinator, device, sensor_type)
        self._attr_unique_id = f"{device.deviceid}_{sensor_type}_humidity"
        self._attr_name = f"{sensor_type.title()} humidity"

    @property
    def native_value(self) -> int | None:
        """Return the humidity."""
        if self._sensor_type == "outdoor":
            return self._device.outdoor_humidity
        return self._device.current_humidity
