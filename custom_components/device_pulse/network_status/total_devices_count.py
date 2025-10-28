"""Sensor platform for Device Pulse - Network Summary."""

from __future__ import annotations

import logging

from custom_components.device_pulse.const import (
    ENTITY_TAG_PING_STATUS,
    INTEGRATION_SUMMARY_TOTAL_DEVICES_COUNT,
    NETWORK_SUMMARY_TOTAL_DEVICES_COUNT,
)
from custom_components.device_pulse.utils import is_tagged_entity_entry

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
import homeassistant.helpers.entity_registry as er
from homeassistant.helpers.event import EventStateChangedData

from .base import NetworkStatusEntity

_LOGGER = logging.getLogger(__name__)


class TotalDevicesCountSensor(SensorEntity, NetworkStatusEntity):
    """Sensor that counts total monitored devices (excluding disabled)."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        """Initialize the sensor."""
        SensorEntity.__init__(self)
        NetworkStatusEntity.__init__(self, hass, config_entry)

        if self.integration:
            self._attr_name = f"{self.integration.friendly_name} Devices"
            self._attr_unique_id = INTEGRATION_SUMMARY_TOTAL_DEVICES_COUNT.format(platform=self.integration.domain)
        else:
            self._attr_name = "Total Devices"
            self._attr_unique_id = NETWORK_SUMMARY_TOTAL_DEVICES_COUNT

        self._attr_icon = "mdi:counter"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_value = 0

    @callback
    def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle state changes."""
        return

    async def _update(self) -> None:
        """Update the count of monitored devices."""
        count = 0
        entity_registry = er.async_get(self.hass)

        for entity_id, entity_entry in entity_registry.entities.items():
            if (
                is_tagged_entity_entry(entity_entry, ENTITY_TAG_PING_STATUS)
                and (
                    not self.config_entry
                    or self.config_entry.entry_id == entity_entry.config_entry_id
                )
                and not entity_entry.disabled
                and entity_id != f"binary_sensor.{self._attr_unique_id}"
            ):
                _LOGGER.debug("Adding device %s to count", entity_id)
                count += 1

        _LOGGER.debug("Devices %s count updated: %s", self.integration.friendly_name if self.integration else "Total", count)
        self._attr_native_value = count
        self.async_write_ha_state()
