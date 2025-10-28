"""Binary sensor platform for Device Pulse."""

import logging

from custom_components.device_pulse.const import ENTITY_TAG_PING_STATUS

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .base import BaseCoordinatorEntity



_LOGGER = logging.getLogger(__name__)

class DevicePingStatusBinarySensor(BaseCoordinatorEntity, BinarySensorEntity):
    """Binary sensor for device ping status."""

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

    @property
    def is_on(self) -> bool:
        """Return true if the device is reachable."""
        return self.coordinator.data.is_alive

