"""Base class for sensors."""

import abc
import logging

from custom_components.device_pulse.coordinator import DevicePingCoordinator
from custom_components.device_pulse.const import DOMAIN
from custom_components.device_pulse.utils import IntegrationData

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)

ATTR_INTEGRATION = "integration"
ATTR_HOST = "host"
ATTR_TAG = "tag"

class BaseCoordinatorEntity(CoordinatorEntity[DevicePingCoordinator], abc.ABC):
    """Base class for sensors."""

    _unrecorded_attributes = frozenset({ATTR_INTEGRATION, ATTR_HOST, ATTR_TAG})

    def __init__(
        self,
        coordinator: DevicePingCoordinator,
        device: dr.DeviceEntry,
        integration: IntegrationData,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._device: dr.DeviceEntry = device
        self._integration: IntegrationData = integration

        # Build unique_id based on identifier
        device_id = next(iter(device.identifiers), (None, device.id))[1]
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{self._tag}"
        self._attr_name = f"{device.name_by_user or device.name} {self._name_suffix}"

        self._configure()

        _LOGGER.debug(
            "Initializing sensor %s (unique_id: %s)",
            self._attr_name,
            self._attr_unique_id,
        )

    @property
    def device_info(self) -> dict:
        """Return device info to link this sensor to the original device."""
        device_info = {}

        if self._device.identifiers:
            device_info["identifiers"] = self._device.identifiers

        if self._device.connections:
            device_info["connections"] = self._device.connections

        if self._device.name:
            device_info["name"] = self._device.name
        if self._device.manufacturer:
            device_info["manufacturer"] = self._device.manufacturer
        if self._device.model:
            device_info["model"] = self._device.model

        return device_info

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional attributes."""
        return {
            ATTR_INTEGRATION: self._integration.domain,
            ATTR_HOST: self.coordinator.ping.ip_address,
            ATTR_TAG: self._tag,
        }

    @property
    @abc.abstractmethod
    def _tag(self) -> str:
        """TAG for the sensor type."""

    @property
    @abc.abstractmethod
    def _name_suffix(self) -> str:
        """Suffix for the sensor name."""

    @abc.abstractmethod
    def _configure(self) -> None:
        """Additional initialization for the sensor."""
