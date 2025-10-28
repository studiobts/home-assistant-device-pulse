from abc import ABC, abstractmethod

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr

class BaseHostResolver(ABC):
    """Base class for integration-specific host resolvers."""

    @staticmethod
    @abstractmethod
    def resolve(config_entry: ConfigEntry, device: dr.DeviceEntry) -> str | None:
        """Return the Host for the given config entry."""
