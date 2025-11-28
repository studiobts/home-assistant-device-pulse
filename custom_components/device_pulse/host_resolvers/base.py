from abc import ABC, abstractmethod
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr

class BaseHostResolver(ABC):
    """Base class for integration-specific host resolvers."""

    @staticmethod
    @abstractmethod
    def resolve(config_entry: ConfigEntry, device: dr.DeviceEntry) -> str | None:
        """Return the Host for the given config entry."""


    @staticmethod
    def device_configuration_url(device: dr.DeviceEntry) -> str | None:
        """Return the hostname of the configuration URL for the given device."""
        if not device.configuration_url:
            return None

        parsed = urlparse(device.configuration_url)
        return parsed.hostname