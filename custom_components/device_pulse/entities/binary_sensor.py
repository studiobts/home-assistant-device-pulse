"""Binary sensor platform for Device Pulse."""

import logging

from custom_components.device_pulse.const import (
    ENTITY_ATTR_STATE_SINCE,
    ENTITY_ATTR_PINGS_FAILED,
    ENTITY_TAG_PING_STATUS
)

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .base import BaseCoordinatorEntity

_LOGGER = logging.getLogger(__name__)

class DevicePingStatusBinarySensor(BaseCoordinatorEntity, BinarySensorEntity, RestoreEntity):
    """Binary sensor for device ping status."""

    def __init__(self, *args, **kwargs):
        """Initialize the sensor."""
        super().__init__(*args, **kwargs)

        self._state_since = None
        self._previous_state = None

    async def async_added_to_hass(self):
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()

        # Restore previous state
        if last_state := await self.async_get_last_state():
            self._previous_state = last_state.state == "on"
            self._state_since = last_state.attributes.get(ENTITY_ATTR_STATE_SINCE, None)
        # Initialize state since if None
        if self._state_since is None:
            self._state_since = dt_util.now().timestamp()

    @property
    def _tag(self) -> str:
        """Prefix for the sensor type."""
        return ENTITY_TAG_PING_STATUS

    @property
    def _name_suffix(self) -> str:
        """Suffix for the sensor name."""
        return "Ping"

    def _configure(self) -> None:
        """Additional initialization for the sensor."""
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        current_state = self.coordinator.data.is_alive

        if self._previous_state is not None and self._previous_state != current_state:
            self._state_since = dt_util.now().timestamp()

        self._previous_state = current_state
        super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool:
        """Return true if the device is reachable."""
        return self.coordinator.data.is_alive

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional attributes."""
        return {
            **super().extra_state_attributes,
            ENTITY_ATTR_STATE_SINCE: self._state_since,
            ENTITY_ATTR_PINGS_FAILED: self.coordinator.failed_pings > 0
        }
