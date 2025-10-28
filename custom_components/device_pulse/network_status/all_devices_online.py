"""Binary sensor platform for Device Pulse."""

import logging

from custom_components.device_pulse.const import (
    ENTITY_TAG_PING_STATUS,
    NETWORK_SUMMARY_ALL_DEVICES_ONLINE_STATUS_ID,
)
from custom_components.device_pulse.utils import is_tagged_entity_entry

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import Event, HomeAssistant, callback
import homeassistant.helpers.entity_registry as er
from homeassistant.helpers.event import EventStateChangedData

from .base import NetworkStatusEntity

_LOGGER = logging.getLogger(__name__)


class AllDevicesOnlineStatusSensor(BinarySensorEntity, NetworkStatusEntity):
    """Binary sensor that indicates if all monitored device are online."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        BinarySensorEntity.__init__(self)
        NetworkStatusEntity.__init__(self, hass)
        self._attr_name = "All Devices Online"
        self._attr_unique_id = NETWORK_SUMMARY_ALL_DEVICES_ONLINE_STATUS_ID
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_is_on = False

    @callback
    def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle state changes."""
        state = event.data.get("new_state")
        if not state:
            return

        state = state.state

        # If state is OFF and sensor is False we have to change status
        # since not all monitored devices are online
        if state == "off" and not self._attr_is_on:
            self._attr_is_on = True
            self.async_write_ha_state()
            _LOGGER.debug("All device online status updated: %s", self._attr_is_on)
        # If state is ON and sensor is True there was at least one monitored
        # device offline, in this case we have to do a full update in order to
        # be sure that all monitored device are online before change status
        elif state == "on" and self._attr_is_on:
            self.hass.async_create_task(self._update())

    async def _update(self) -> None:
        """Update the status based on all ping sensors."""
        all_online = True
        entity_registry = er.async_get(self.hass)

        for entity_id, entity_entry in entity_registry.entities.items():
            if (
                is_tagged_entity_entry(entity_entry, ENTITY_TAG_PING_STATUS)
                and not entity_entry.disabled
                and entity_id != self.entity_id
                and (state := self.hass.states.get(entity_id))
                and state.state == "off"
            ):
                all_online = False
                break

        self._attr_is_on = not all_online
        self.async_write_ha_state()

        _LOGGER.debug("All device online status updated: %s", self._attr_is_on)
