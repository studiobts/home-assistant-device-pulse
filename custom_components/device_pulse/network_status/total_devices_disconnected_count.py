"""Sensor platform for Device Pulse - Network Summary."""

from __future__ import annotations

import logging

from custom_components.device_pulse.const import (
    ENTITY_ATTR_INTEGRATION_DOMAIN,
    ENTITY_TAG_PING_STATUS,
    INTEGRATION_SUMMARY_TOTAL_DEVICES_OFFLINE_COUNT,
    NETWORK_SUMMARY_TOTAL_DEVICES_OFFLINE_COUNT
)
from custom_components.device_pulse.utils import is_tagged_entity_entry

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
import homeassistant.helpers.entity_registry as er
from homeassistant.helpers.event import EventStateChangedData

from .base import NetworkStatusEntity

_LOGGER = logging.getLogger(__name__)


class TotalDevicesDisconnectedCountSensor(SensorEntity, NetworkStatusEntity):
    """Sensor that counts offline devices (excluding disabled)."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        """Initialize the sensor."""
        SensorEntity.__init__(self)
        NetworkStatusEntity.__init__(self, hass, config_entry)

        if self.integration:
            self._attr_name = f"{self.integration.friendly_name} Devices Offline"
            self._attr_unique_id = INTEGRATION_SUMMARY_TOTAL_DEVICES_OFFLINE_COUNT.format(platform=self.integration.domain)
        else:
            self._attr_name = "Devices Offline"
            self._attr_unique_id = NETWORK_SUMMARY_TOTAL_DEVICES_OFFLINE_COUNT

        self._attr_icon = "mdi:lan-disconnect"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_value = 0

        self._offline_device_ids: list = []
        self._went_offline_device_ids: list = []
        self._came_online_device_ids: list = []

    @callback
    def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle state changes."""
        if self.config_entry:
            entity_registry = er.async_get(self.hass)
            entity_entry = entity_registry.async_get(event.data.get("entity_id"))

            if self.config_entry.entry_id != entity_entry.config_entry_id:
                return

        self.hass.async_create_task(self._update())

    async def _update(self) -> None:
        """Update the count of offline devices."""
        devices_offline = []
        entity_registry = er.async_get(self.hass)

        for entity_id, entity_entry in entity_registry.entities.items():
            if (
                is_tagged_entity_entry(entity_entry, ENTITY_TAG_PING_STATUS)
                and not entity_entry.disabled
            ):
                state = self.hass.states.get(entity_id)
                if (
                    state
                    and state.state == "off"
                    and (not self.integration or self.integration.domain == state.attributes.get(ENTITY_ATTR_INTEGRATION_DOMAIN))
                ):
                    devices_offline.append(entity_entry.device_id)

        self._went_offline_device_ids = list(set(devices_offline) - set(self._offline_device_ids))
        self._came_online_device_ids = list(set(self._offline_device_ids) - set(devices_offline))
        self._offline_device_ids = devices_offline
        self._attr_native_value = len(devices_offline)
        self.async_write_ha_state()

        _LOGGER.debug(
            "Offline Devices %s count updated: %s",
            self.integration.friendly_name if self.integration else "Total",
            self._attr_native_value
        )


    @property
    def extra_state_attributes(self):
        return {
            "offline_device_ids": self._offline_device_ids,
            "went_offline_device_ids": self._went_offline_device_ids,
            "came_online_device_ids": self._came_online_device_ids,
        }
